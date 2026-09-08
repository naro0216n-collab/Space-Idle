from __future__ import annotations

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import PathPolicy, CargoOrder, RecurringCargoRule


class TransportOrderMixin:
        def create_recurring_rule(
            self, source_id: SpatialNodeId, destination_id: SpatialNodeId, resource_id: DefinitionId,
            target_stock_t: float, batch_t: float, priority: int, path: tuple[RouteId, ...] | None = None,
            mode_by_route: dict[RouteId, str] | None = None,
            path_policy: PathPolicy = PathPolicy.FASTEST,
        ) -> EntityId:
            if source_id == destination_id:
                raise ValueError("logistics rule endpoints must differ")
            if target_stock_t < 0 or batch_t <= 0:
                raise ValueError("invalid recurring cargo rule quantities")
            selected_modes = {} if mode_by_route is None else dict(mode_by_route)
            if path is None and selected_modes:
                raise ValueError("explicit transport modes require an explicit route path for recurring rules")
            if path is not None:
                self.validate_path_structure(source_id, destination_id, path)
                self.validate_mode_selection(path, selected_modes)
            self._rule_counter += 1
            rule_id = EntityId(f"logistics.rule.{self._rule_counter}")
            self.recurring_rules[rule_id] = RecurringCargoRule(
                rule_id, source_id, destination_id, resource_id, target_stock_t, batch_t, priority,
                path, selected_modes, path_policy, False,
            )
            return rule_id

        def recurring_rule_blockers(self, rule_id: EntityId, day: int = 0) -> tuple[str, ...]:
            rule = self.recurring_rules[rule_id]
            blockers: list[str] = []
            if rule.paused:
                blockers.append("manual_pause")
            projected = self.inventory.amount(rule.destination_id, rule.resource_id) + self._pipeline_remaining(rule.id)
            if projected + 1e-9 >= rule.target_stock_t:
                blockers.append("target_satisfied")
                return tuple(blockers)
            if self.inventory.available(rule.source_id, rule.resource_id) <= 1e-12:
                blockers.append("source_stock")
            try:
                selected = self.find_path(rule.source_id, rule.destination_id, day, rule.path_policy) if rule.path is None else rule.path
                self.validate_path_structure(rule.source_id, rule.destination_id, selected)
            except (KeyError, ValueError):
                blockers.append("route_unavailable")
                return tuple(dict.fromkeys(blockers))
            # Only the current first leg must have a vehicle/service now. Later legs
            # may become usable after spacecraft and cargo reach the transfer node.
            if selected:
                first = selected[0]
                blockers.extend(
                    f"route:{first}:{reason}"
                    for reason in self.route_operational_failures(first, day, rule.mode_by_route.get(first))
                )
            free = self.inventory.free_capacity(rule.destination_id, rule.resource_id)
            if free is not None and free <= 1e-12:
                blockers.append("destination_storage")
            return tuple(dict.fromkeys(blockers))

        def pause_recurring_rule(self, rule_id: EntityId) -> None:
            self.recurring_rules[rule_id].paused = True

        def resume_recurring_rule(self, rule_id: EntityId) -> None:
            self.recurring_rules[rule_id].paused = False

        def delete_recurring_rule(self, rule_id: EntityId) -> None:
            self.recurring_rules.pop(rule_id)

        def _pipeline_remaining(self, rule_id: EntityId) -> float:
            return sum(
                max(0.0, order.amount_t - order.delivered_t)
                for order in self.orders.values()
                if order.owner_kind == "logistics_rule" and order.owner_id == rule_id and not self.order_complete(order.id)
            )

        def advance_automation(self, day: int) -> None:
            for rule in sorted(self.recurring_rules.values(), key=lambda row: (-row.priority, str(row.id))):
                if rule.paused:
                    continue
                projected = self.inventory.amount(rule.destination_id, rule.resource_id) + self._pipeline_remaining(rule.id)
                gap = rule.target_stock_t - projected
                if gap <= 1e-9:
                    continue
                amount = min(rule.batch_t, gap, self.inventory.available(rule.source_id, rule.resource_id))
                if amount <= 1e-9:
                    continue
                path = rule.path
                if not self.can_submit(rule.source_id, rule.destination_id, rule.resource_id, amount, day, path, rule.mode_by_route, rule.path_policy):
                    continue
                self.submit_order(
                    rule.source_id, rule.destination_id, rule.resource_id, amount, rule.priority,
                    "logistics_rule", rule.id, day=day, path=path, mode_by_route=rule.mode_by_route,
                    path_policy=rule.path_policy,
                )

        def can_submit(
            self, source_id: SpatialNodeId, destination_id: SpatialNodeId, resource_id: DefinitionId,
            amount_t: float, day: int = 0, path: tuple[RouteId, ...] | None = None,
            mode_by_route: dict[RouteId, str] | None = None,
            path_policy: PathPolicy = PathPolicy.FASTEST,
        ) -> bool:
            if source_id == destination_id or amount_t <= 0:
                return False
            if self.inventory.available(source_id, resource_id) + 1e-9 < amount_t:
                return False
            try:
                selected = self.find_path(source_id, destination_id, day, path_policy) if path is None else path
                selected_modes = {} if mode_by_route is None else dict(mode_by_route)
                if path is None and not selected_modes:
                    auto_modes = self._automatic_mode_plan(selected, day, path_policy)
                    if auto_modes is None:
                        return False
                    selected_modes = auto_modes
                self.validate_path(source_id, destination_id, selected, day, selected_modes)
                if selected and self.route_operational_failures(selected[0], day, selected_modes.get(selected[0])):
                    return False
            except (KeyError, ValueError):
                return False
            return True

        def submit_order(
            self, source_id: SpatialNodeId, destination_id: SpatialNodeId, resource_id: DefinitionId,
            amount_t: float, priority: int, owner_kind: str, owner_id: EntityId, *, day: int = 0,
            path: tuple[RouteId, ...] | None = None, mode_by_route: dict[RouteId, str] | None = None,
            path_policy: PathPolicy = PathPolicy.FASTEST,
        ) -> CargoOrderId:
            if source_id == destination_id:
                raise ValueError("cargo order endpoints must differ")
            if amount_t <= 0:
                raise ValueError("cargo amount must be positive")
            selected_path = self.find_path(source_id, destination_id, day, path_policy) if path is None else path
            selected_modes = {} if mode_by_route is None else dict(mode_by_route)
            if path is None and not selected_modes:
                auto_modes = self._automatic_mode_plan(selected_path, day, path_policy)
                if auto_modes is None:
                    raise ValueError("automatic route has no executable transfer or continuous carrier plan")
                selected_modes = auto_modes
            self.validate_path(source_id, destination_id, selected_path, day, selected_modes)
            if selected_path and self.route_operational_failures(selected_path[0], day, selected_modes.get(selected_path[0])):
                raise ValueError("first cargo leg is not currently dispatchable")
            self._counter += 1
            order_id = CargoOrderId(f"cargo.{self._counter}")
            owner = self._waiting_owner(order_id, 0)
            if not self.inventory.stage_unreserved(owner, source_id, resource_id, amount_t):
                self._counter -= 1
                raise ValueError(f"insufficient source stock: {resource_id}")
            self.orders[order_id] = CargoOrder(
                order_id, source_id, destination_id, resource_id, amount_t, priority, owner_kind, owner_id,
                selected_path, selected_modes, path_policy,
            )
            self.waiting[(order_id, 0)] = amount_t
            return order_id

        def order_complete(self, order_id: CargoOrderId) -> bool:
            order = self.orders[order_id]
            return order.delivered_t + 1e-9 >= order.amount_t
