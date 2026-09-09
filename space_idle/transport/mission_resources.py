from __future__ import annotations

from dataclasses import dataclass

from ..shared import DefinitionId
from .models import RouteDef, VehicleDef, VehicleState


_EPS = 1e-9


@dataclass(frozen=True)
class VehicleLegResourcePlan:
    """Side-effect-free resource result for one owned-vehicle transport leg."""

    mission_cost_musd: float
    required_propellant_t: float
    refuel_t: float
    ending_propellant_t: float
    blockers: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.blockers


def evaluate_vehicle_leg_resources(
    vehicle: VehicleDef,
    route: RouteDef,
    cargo_t: float,
    starting_propellant_t: float,
    *,
    funds_musd: float,
    vehicle_at_origin: bool,
    refueling_available: bool,
    propellant_stock_t: float,
) -> VehicleLegResourcePlan:
    """Evaluate fuel/funds for one leg without mutating game state.

    Route/operation compatibility and payload limits remain transport-planning
    responsibilities. Both capacity projection and mission execution use this
    function for the resource accounting that follows those physical checks.
    """

    if cargo_t < -_EPS:
        raise ValueError("cargo mass must be non-negative")
    blockers: list[str] = []
    mission_cost = (
        vehicle.operating_cost_musd_per_mission
        + max(0.0, cargo_t) * vehicle.operating_cost_musd_per_cargo_t
    )
    required = vehicle.propellant_t(route, max(0.0, cargo_t))
    if required > vehicle.propellant_capacity_t + _EPS:
        blockers.append("propellant_capacity")

    refuel_t = max(0.0, required - max(0.0, starting_propellant_t))
    if refuel_t > _EPS:
        if vehicle.propellant_resource_id is None:
            blockers.append("propellant_resource")
        if not vehicle_at_origin:
            blockers.append("vehicle_location")
        if not refueling_available:
            blockers.append("vehicle_refueling")
        if propellant_stock_t + _EPS < refuel_t:
            blockers.append("propellant_stock")
    if funds_musd + _EPS < mission_cost:
        blockers.append("funds")

    ending = max(0.0, starting_propellant_t + refuel_t - required)
    return VehicleLegResourcePlan(
        mission_cost,
        required,
        refuel_t,
        ending,
        tuple(dict.fromkeys(blockers)),
    )


class TransportMissionResourcesMixin:
    """Authoritative owned-vehicle leg resource accounting and mutation."""

    def _vehicle_leg_resource_plan(
        self,
        state: VehicleState,
        vehicle: VehicleDef,
        route: RouteDef,
        cargo_t: float,
        day: int,
        *,
        starting_propellant_t: float | None = None,
        funds_musd: float | None = None,
        propellant_stock_t: float | None = None,
        vehicle_at_origin: bool | None = None,
    ) -> VehicleLegResourcePlan:
        resource_id: DefinitionId | None = vehicle.propellant_resource_id
        stock = 0.0
        if resource_id is not None:
            stock = (
                self.inventory.available(route.origin_id, resource_id)
                if propellant_stock_t is None
                else propellant_stock_t
            )
        return evaluate_vehicle_leg_resources(
            vehicle,
            route,
            cargo_t,
            state.propellant_t if starting_propellant_t is None else starting_propellant_t,
            funds_musd=self.account.funds_musd if funds_musd is None else funds_musd,
            vehicle_at_origin=(state.location_id == route.origin_id)
            if vehicle_at_origin is None
            else vehicle_at_origin,
            refueling_available=self._has_available_capability(
                route.origin_id, "vehicle_refueling", day
            ),
            propellant_stock_t=stock,
        )

    def _pay_vehicle_mission(
        self,
        state: VehicleState,
        vehicle: VehicleDef,
        route: RouteDef,
        cargo_t: float,
        day: int,
    ) -> bool:
        plan = self._vehicle_leg_resource_plan(state, vehicle, route, cargo_t, day)
        if not plan.feasible:
            return False
        if not self.account.spend(plan.mission_cost_musd):
            return False
        if plan.refuel_t > _EPS:
            resource_id = vehicle.propellant_resource_id
            if resource_id is None or not self.inventory.take_unreserved(
                route.origin_id, resource_id, plan.refuel_t
            ):
                self.account.earn(plan.mission_cost_musd)
                return False
        state.propellant_t = plan.ending_propellant_t
        return True
