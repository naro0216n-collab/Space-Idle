from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .facilities import FacilityBook
from .logistics import LogisticsService
from .power import PowerService
from .shared import AccountState, ContractId, DefinitionId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements


@dataclass(frozen=True)
class CapabilityContractTemplate:
    id: DefinitionId
    display_name: str
    site_requirements: SiteRequirements
    duration_days: int
    reward_musd: float
    target_location_id: SpatialNodeId | None = None


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
    logistics: LogisticsService
    power: PowerService
    account: AccountState
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
        self, template: CapabilityContractTemplate, day: int
    ) -> bool:
        locations = (
            (template.target_location_id,)
            if template.target_location_id is not None
            else tuple(self.facilities.environment.graph.nodes)
        )
        return any(
            not evaluate_site_requirements(
                template.site_requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
                self.power.snapshot(location_id, self.facilities, day),
            )
            for location_id in locations
        )

    def advance_day(self, day: int) -> None:
        for state in self.contracts.values():
            if state.status not in {ContractStatus.OFFERED, ContractStatus.ACCEPTED}:
                continue
            template = self.templates[state.template_id]
            if state.status == ContractStatus.ACCEPTED and self._capability_contract_complete(
                template, day
            ):
                state.status = ContractStatus.COMPLETED
                self.account.earn(template.reward_musd)
                continue
            if day > state.deadline_day:
                state.status = ContractStatus.FAILED
