from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from enum import Enum

from .facilities import FacilityBook
from .logistics import LogisticsService
from .power import PowerService
from .shared import AccountState, CargoOrderId, ContractId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements


@dataclass(frozen=True)
class CapabilityContractTemplate:
    id: DefinitionId
    display_name: str
    site_requirements: SiteRequirements
    duration_days: int
    reward_musd: float
    target_location_id: SpatialNodeId | None = None


@dataclass(frozen=True)
class CargoContractTemplate:
    id: DefinitionId
    display_name: str
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    cargo_t: float
    duration_days: int
    reward_musd: float
    priority: int


ContractTemplate = CapabilityContractTemplate | CargoContractTemplate


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
    cargo_order_id: CargoOrderId | None = None


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
        self.contracts[cid] = ContractState(cid, template_id, day, day + template.duration_days)
        return cid

    def accept(self, contract_id: ContractId, day: int) -> None:
        state = self.contracts[contract_id]
        template = self.templates[state.template_id]
        if state.status != ContractStatus.OFFERED:
            raise ValueError("contract not offered")
        if day > state.deadline_day:
            raise ValueError("contract deadline has passed")
        # Acceptance commits to the objective but does not choose a logistics
        # path on the player's behalf. Cargo dispatch is a separate decision.
        state.status = ContractStatus.ACCEPTED

    def dispatch_cargo(
        self,
        contract_id: ContractId,
        day: int,
        *,
        path: tuple[RouteId, ...] | None = None,
        mode_by_route: dict[RouteId, str] | None = None,
    ) -> CargoOrderId:
        state = self.contracts[contract_id]
        template = self.templates[state.template_id]
        if not isinstance(template, CargoContractTemplate):
            raise ValueError("contract is not a cargo contract")
        if state.status != ContractStatus.ACCEPTED:
            raise ValueError("cargo contract must be accepted before dispatch")
        if state.cargo_order_id is not None:
            raise ValueError("cargo contract has already been dispatched")
        if day > state.deadline_day:
            raise ValueError("contract deadline has passed")
        order_id = self.logistics.submit_order(
            template.source_id,
            template.destination_id,
            template.resource_id,
            template.cargo_t,
            template.priority,
            "contract",
            EntityId(contract_id),
            day=day,
            path=path,
            mode_by_route=mode_by_route,
        )
        state.cargo_order_id = order_id
        return order_id

    def decline(self, contract_id: ContractId) -> None:
        state = self.contracts[contract_id]
        if state.status != ContractStatus.OFFERED:
            raise ValueError("contract not offered")
        state.status = ContractStatus.DECLINED

    def _capability_contract_complete(self, template: CapabilityContractTemplate, day: int) -> bool:
        if template.target_location_id is not None:
            locations = (template.target_location_id,)
        else:
            locations = tuple(self.facilities.environment.graph.nodes)
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
            if state.status == ContractStatus.ACCEPTED and isinstance(template, CapabilityContractTemplate):
                if self._capability_contract_complete(template, day):
                    state.status = ContractStatus.COMPLETED
                    self.account.earn(template.reward_musd)
                    continue
            if state.status == ContractStatus.ACCEPTED and isinstance(template, CargoContractTemplate):
                if state.cargo_order_id is not None and self.logistics.order_complete(state.cargo_order_id):
                    if day <= state.deadline_day:
                        state.status = ContractStatus.COMPLETED
                        self.account.earn(template.reward_musd)
                    else:
                        state.status = ContractStatus.FAILED
                    continue
            if day > state.deadline_day:
                state.status = ContractStatus.FAILED
