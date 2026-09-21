from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .facilities import FacilityBook
from .power import PowerService, PowerSnapshot
from .service_capacity import ServiceCapacityRegistry
from .shared import ContractId, DefinitionId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements


@dataclass(frozen=True)
class CapabilityContractTemplate:
    id: DefinitionId
    display_name: str
    site_requirements: SiteRequirements
    duration_days: int
    target_operational_node_id: SpatialNodeId | None = None


ContractTemplate = CapabilityContractTemplate


class ContractStatus(str, Enum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    DECLINED = "declined"


@dataclass
class ContractState:
    id: ContractId
    template_id: DefinitionId
    offered_day: int
    deadline_day: int
    status: ContractStatus = ContractStatus.OFFERED


@dataclass
class ContractService:
    templates: dict[DefinitionId, ContractTemplate]
    facilities: FacilityBook
    power: PowerService
    service_capacity_registry: ServiceCapacityRegistry
    contracts: dict[ContractId, ContractState] = field(default_factory=dict)
    _counter: int = 0

    def offer(self, template_id: DefinitionId, day: int) -> ContractId:
        template = self.templates[template_id]
        if template.duration_days < 0:
            raise ValueError("contract duration must be non-negative")
        self._counter += 1
        cid = ContractId(f"contract.{self._counter}")
        self.contracts[cid] = ContractState(
            cid, template_id, day, day + template.duration_days
        )
        return cid

    def accept(self, contract_id: ContractId, day: int) -> None:
        state = self.contracts[contract_id]
        if state.status != ContractStatus.OFFERED:
            raise ValueError("contract not offered")
        if day > state.deadline_day:
            raise ValueError("contract deadline has passed")
        state.status = ContractStatus.ACCEPTED

    def decline(self, contract_id: ContractId) -> None:
        state = self.contracts[contract_id]
        if state.status != ContractStatus.OFFERED:
            raise ValueError("contract not offered")
        state.status = ContractStatus.DECLINED

    def _capability_contract_complete(
        self,
        template: CapabilityContractTemplate,
        day: int,
    ) -> bool:
        locations = (
            (template.target_operational_node_id,)
            if template.target_operational_node_id is not None
            else self.facilities.environment.graph.operational_node_ids()
        )
        return any(
            not evaluate_site_requirements(
                template.site_requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
            )
            for location_id in locations
        )

    def advance_day(
        self,
        day: int,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> None:
        for state in self.contracts.values():
            if state.status not in {ContractStatus.OFFERED, ContractStatus.ACCEPTED}:
                continue
            template = self.templates[state.template_id]
            if state.status == ContractStatus.ACCEPTED and self._capability_contract_complete(
                template, day
            ):
                state.status = ContractStatus.COMPLETED
                continue
            if day > state.deadline_day:
                state.status = ContractStatus.FAILED
