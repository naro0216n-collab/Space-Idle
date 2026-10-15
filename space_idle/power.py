from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import TypeAlias

from .facilities import FacilityBook, FacilityLifecycle, FacilityState
from .service_capacity import ServiceCapacityRequest, allocate_service_capacity
from .shared import DefinitionId, EntityId, SpatialNodeId
from .spatial import EnvironmentResolver, IlluminationField, SpatialContextId


@dataclass(frozen=True)
class FixedGeneration:
    mw: float


@dataclass(frozen=True)
class SolarGeneration:
    rated_mw_at_reference_flux: float
    reference_flux_w_m2: float


GenerationModel: TypeAlias = FixedGeneration | SolarGeneration


@dataclass(frozen=True)
class PowerSpec:
    generation: GenerationModel | None = None
    load_mw: float = 0.0
    # Load required even while the facility is manually paused (e.g.
    # cryogenic hold, containment, safe-state control). It never produces
    # active domain output or capability while paused.
    standby_load_mw: float = 0.0
    beam_transmit_capacity_mw: float = 0.0
    beam_receive_capacity_mw: float = 0.0
    beam_transfer_efficiency: float = 0.75
    beam_range_km: float = 600000000.0

    def __post_init__(self) -> None:
        for amount in (self.load_mw, self.standby_load_mw, self.beam_transmit_capacity_mw,
                       self.beam_receive_capacity_mw, self.beam_range_km):
            if not math.isfinite(amount) or amount < 0:
                raise ValueError("power load, beam capacity and range must be finite and nonnegative")
        if not 0 < self.beam_transfer_efficiency <= 1:
            raise ValueError("beam energy transmission efficiency must be in (0,1]")


@dataclass(frozen=True)
class PowerLink:
    """Player-assigned endpoints and target power; delivery is always derived."""
    source_facility_id: EntityId
    receiver_facility_id: EntityId
    requested_mw: float

    def __post_init__(self) -> None:
        if self.source_facility_id == self.receiver_facility_id:
            raise ValueError("power link endpoints must differ")
        if not math.isfinite(self.requested_mw) or self.requested_mw <= 0:
            raise ValueError("power transfer target must be positive and finite")


@dataclass(frozen=True)
class PowerPhysicalSnapshot:
    operational_node_id: SpatialNodeId
    generation_mw_by_facility: dict[EntityId, float]
    requests: tuple[ServiceCapacityRequest, ...]
    demand_mw: float

    @property
    def nominal_generation_mw(self) -> float:
        return sum(self.generation_mw_by_facility.values())


@dataclass(frozen=True)
class PowerSnapshot:
    generation_mw: float
    demand_mw: float
    allocated_mw: float
    utilization_by_facility: dict[EntityId, float]
    maintenance_factor_by_facility: dict[EntityId, float]
    imported_mw: float = 0.0
    exported_mw: float = 0.0

    @property
    def site_utilization(self) -> float:
        if self.demand_mw <= 1e-9:
            return 1.0
        return min(1.0, self.allocated_mw / self.demand_mw)


@dataclass
class PowerService:
    SERVICE_TYPE = "power"

    @staticmethod
    def _request_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"service.power:{facility_id}")

    specs: dict[DefinitionId, PowerSpec]
    environment: EnvironmentResolver
    links: dict[tuple[EntityId, EntityId], PowerLink] = field(default_factory=dict)

    def configure_link(self, source: EntityId, receiver: EntityId, target_mw: float,
                       facilities: FacilityBook) -> PowerLink:
        link = PowerLink(source, receiver, target_mw)
        src = facilities.facilities[source]
        dst = facilities.facilities[receiver]
        if src.operational_node_id == dst.operational_node_id:
            raise ValueError("beamed power transfer needs distinct Operational Nodes")
        sender_spec = self.specs.get(src.definition_id)
        receiver_spec = self.specs.get(dst.definition_id)
        if sender_spec is None or sender_spec.beam_transmit_capacity_mw <= 0:
            raise ValueError("source Facility cannot transmit power")
        if receiver_spec is None or receiver_spec.beam_receive_capacity_mw <= 0:
            raise ValueError("destination Facility cannot receive power")
        self.links[(source, receiver)] = link
        return link

    def delete_link(self, source: EntityId, receiver: EntityId) -> None:
        del self.links[(source, receiver)]

    def facility_decommission_blockers(self, facility_id: EntityId):
        from .facility_lifecycle import FacilityLifecycleBlocker
        if any(facility_id in pair for pair in self.links):
            return (FacilityLifecycleBlocker("power_link", "explicit power transfer link must be cleared"),)
        return ()


    def resolve_network_snapshots(
        self, physical_by_node: dict[SpatialNodeId, PowerPhysicalSnapshot],
        facilities: FacilityBook, day: int,
        maintenance_factors: dict[EntityId, float] | None = None,
    ) -> dict[SpatialNodeId, PowerSnapshot]:
        """One physical power ledger for local generation and cross-node losses.

        Only energy remaining after local nominal demand may be exported. Power
        imported at a receiver cannot be retransmitted on the same tick. No
        stored derived link result or cross-Domain Inventory account exists.
        """
        if not self.links:
            return {
                node: self.resolve_snapshot(physical, maintenance_factors)
                for node, physical in physical_by_node.items()
            }
        factors = maintenance_factors or {}
        local_generation = {
            node: math.fsum(value * max(0., min(1., factors.get(fid, 1.)))
                            for fid, value in physical.generation_mw_by_facility.items())
            for node, physical in physical_by_node.items()
        }
        remaining_surplus = {
            node: max(0., generation - physical_by_node[node].demand_mw)
            for node, generation in local_generation.items()
        }
        transmitter_remaining: dict[EntityId, float] = {}
        receiver_remaining: dict[EntityId, float] = {}
        exported: dict[SpatialNodeId, float] = {}
        imported: dict[SpatialNodeId, float] = {}
        for link in sorted(self.links.values(), key=lambda item:
                           (str(item.source_facility_id), str(item.receiver_facility_id))):
            src = facilities.facilities.get(link.source_facility_id)
            dst = facilities.facilities.get(link.receiver_facility_id)
            if src is None or dst is None or src.operational_node_id == dst.operational_node_id:
                continue
            if src.operational_node_id not in local_generation or dst.operational_node_id not in local_generation:
                continue
            if (src.lifecycle is not FacilityLifecycle.NORMAL or src.paused or
                dst.lifecycle is not FacilityLifecycle.NORMAL or dst.paused or
                not facilities.is_environmentally_compatible(src, day) or
                not facilities.is_environmentally_compatible(dst, day)):
                continue
            sender = self.specs.get(src.definition_id)
            receiver = self.specs.get(dst.definition_id)
            if sender is None or receiver is None:
                continue
            if not sender.beam_transmit_capacity_mw or not receiver.beam_receive_capacity_mw:
                continue
            separation = self.environment.graph.characteristic_transport_separation(
                facilities.facility_environment_context(src),
                facilities.facility_environment_context(dst),
            )
            if (separation.distance_km is None or
                    separation.distance_km > min(sender.beam_range_km, receiver.beam_range_km)):
                continue
            efficiency = min(sender.beam_transfer_efficiency, receiver.beam_transfer_efficiency)
            source_node = src.operational_node_id
            destination_node = dst.operational_node_id
            send_limit = transmitter_remaining.setdefault(
                src.id, sender.beam_transmit_capacity_mw * src.level
                * max(0., min(1., factors.get(src.id, 1.)))
            )
            receive_limit = receiver_remaining.setdefault(
                dst.id, receiver.beam_receive_capacity_mw * dst.level
                * max(0., min(1., factors.get(dst.id, 1.)))
            )
            sent = min(link.requested_mw, remaining_surplus[source_node],
                       send_limit, receive_limit / efficiency)
            if sent <= 1e-12:
                continue
            delivered = sent * efficiency
            remaining_surplus[source_node] -= sent
            transmitter_remaining[src.id] -= sent
            receiver_remaining[dst.id] -= delivered
            exported[source_node] = exported.get(source_node, 0.) + sent
            imported[destination_node] = imported.get(destination_node, 0.) + delivered
        resolved: dict[SpatialNodeId, PowerSnapshot] = {}
        for node, physical in physical_by_node.items():
            # The donor's actual generation is reduced by all transmitted MW;
            # receiver's generation is increased only by delivered MW.
            local = self.resolve_snapshot(physical, maintenance_factors)
            available = local_generation[node] - exported.get(node, 0.) + imported.get(node, 0.)
            plan = allocate_service_capacity(
                physical.requests,
                nominal_supply={(node, self.SERVICE_TYPE): max(0., available)},
            )
            utilization = {}
            allocated = 0.
            for request in physical.requests:
                amount = plan.allocated(request.id)
                allocated += amount
                utilization[request.owner_id] = (1. if request.requested_rate <= 1e-12
                    else max(0., min(1., amount / request.requested_rate)))
            resolved[node] = replace(local, generation_mw=available,
                allocated_mw=allocated, utilization_by_facility=utilization,
                imported_mw=imported.get(node, 0.), exported_mw=exported.get(node, 0.))
        return resolved

    def _generation_at_context(self, spec: PowerSpec, context_id: SpatialContextId) -> float:
        """Same physical generator for installed Assets and prospective Build sites."""
        model = spec.generation
        if model is None:
            return 0.0
        if isinstance(model, FixedGeneration):
            return model.mw
        illumination = self.environment.get(context_id, IlluminationField)
        if illumination is None:
            return 0.0
        return (
            model.rated_mw_at_reference_flux
            * illumination.solar_flux_w_m2
            / model.reference_flux_w_m2
            * illumination.availability
        )

    def nominal_for_definition_at_context(
        self, definition_id: DefinitionId, context_id: SpatialContextId,
    ) -> tuple[float, float]:
        """Unmaintained active generation/load at a site, without installing it.

        Acquisition, actual eligibility, maintenance and shared Power allocation
        remain the owning Domains' responsibility. A missing PowerSpec supplies
        neither capacity nor an invented load.
        """
        spec = self.specs.get(definition_id)
        if spec is None:
            return 0.0, 0.0
        return self._generation_at_context(spec, context_id), spec.load_mw

    def _generation(self, spec: PowerSpec, facility: FacilityState, facilities: FacilityBook) -> float:
        return self._generation_at_context(
            spec, facilities.facility_environment_context(facility),
        )

    def physical_snapshot(
        self, operational_node_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> PowerPhysicalSnapshot:
        """Capture nominal power supply and load intent before allocation."""
        requests: list[ServiceCapacityRequest] = []
        generation_by_facility: dict[EntityId, float] = {}
        demand = 0.0
        for facility in facilities.all_at(operational_node_id):
            # Irreversible decommissioning removes active power supply and
            # operating demand, not merely the facility's Capability supply.
            if facility.lifecycle is FacilityLifecycle.DECOMMISSIONING:
                continue
            if not facilities.is_environmentally_compatible(facility, day):
                continue
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            if not facility.paused:
                generation_by_facility[facility.id] = self._generation(
                    spec, facility, facilities
                ) * facility.level
            load = (spec.standby_load_mw if facility.paused else spec.load_mw) * facility.level
            if load > 0:
                priority = facility.activity_priority
                requests.append(ServiceCapacityRequest(
                    self._request_id(facility.id),
                    operational_node_id,
                    self.SERVICE_TYPE,
                    load,
                    priority,
                    "facility",
                    facility.id,
                    "power_load",
                ))
                demand += load
        return PowerPhysicalSnapshot(
            operational_node_id,
            generation_by_facility,
            tuple(requests),
            demand,
        )

    def resolve_snapshot(
        self,
        physical: PowerPhysicalSnapshot,
        maintenance_factors: dict[EntityId, float] | None = None,
    ) -> PowerSnapshot:
        """Resolve current-tick power from physical state and upstream allocation."""
        factors = maintenance_factors or {}
        facility_ids = (
            set(factors)
            | set(physical.generation_mw_by_facility)
            | {request.owner_id for request in physical.requests}
        )
        resolved_factors = {
            facility_id: max(0.0, min(1.0, factors.get(facility_id, 1.0)))
            for facility_id in facility_ids
        }
        generation = sum(
            amount * resolved_factors.get(facility_id, 1.0)
            for facility_id, amount in physical.generation_mw_by_facility.items()
        )
        plan = allocate_service_capacity(
            physical.requests,
            nominal_supply={(physical.operational_node_id, self.SERVICE_TYPE): generation},
        )
        utilization: dict[EntityId, float] = {}
        allocated = 0.0
        for request in physical.requests:
            amount = plan.allocated(request.id)
            allocated += amount
            utilization[request.owner_id] = (
                1.0
                if request.requested_rate <= 1e-12
                else max(0.0, min(1.0, amount / request.requested_rate))
            )
        return PowerSnapshot(
            generation,
            physical.demand_mw,
            allocated,
            utilization,
            resolved_factors,
        )

    def snapshot(
        self, operational_node_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> PowerSnapshot:
        """Resolve a nominal standalone snapshot without transient maintenance state.

        Simulation execution supplies current-tick maintenance fulfillment through
        ``resolve_snapshot``. Direct callers receive a dependency-neutral snapshot
        and therefore cannot accidentally reuse a previous tick's allocation.
        """
        return self.resolve_snapshot(
            self.physical_snapshot(operational_node_id, facilities, day)
        )
