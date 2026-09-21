from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import (
    ATMOSPHERIC_ENTRY,
    LANDING,
    POWERED_ASCENT,
    SPACEFLIGHT,
    SURFACE_TRANSPORT,
    AtmosphericEntryCapability,
    LandingCapability,
    OperationCapability,
    PoweredAscentCapability,
    SpaceflightCapability,
    SurfaceTransportCapability,
    TransportOperationRequirement,
)


@dataclass(frozen=True)
class OperationEvaluationContext:
    transit_days: int
    origin_surface: tuple[float, float] | None
    destination_surface: tuple[float, float] | None
    surface_distance_km: float | None = None


OperationEvaluator = Callable[[TransportOperationRequirement, OperationCapability, OperationEvaluationContext], tuple[str, ...]]


class OperationEvaluatorRegistry:
    """Open registry for transport operation semantics.

    Adding an operation requires registering one evaluator and defining a
    capability object with a matching ``operation_type``; VehicleDef and the
    planner do not need a new field or central switch branch.
    """

    def __init__(self) -> None:
        self._evaluators: dict[str, tuple[type, OperationEvaluator]] = {}

    def register(self, operation_type: str, capability_type: type, evaluator: OperationEvaluator) -> None:
        if not operation_type:
            raise ValueError("operation type must be non-empty")
        if operation_type in self._evaluators:
            raise ValueError(f"transport operation evaluator already registered: {operation_type}")
        self._evaluators[operation_type] = (capability_type, evaluator)

    def operation_types(self) -> frozenset[str]:
        return frozenset(self._evaluators)

    def supports(self, operation_type: str) -> bool:
        return operation_type in self._evaluators

    def evaluate(
        self,
        requirement: TransportOperationRequirement,
        capability: OperationCapability | None,
        context: OperationEvaluationContext,
    ) -> tuple[str, ...]:
        row = self._evaluators.get(requirement.operation_type)
        if row is None:
            return (f"operation:{requirement.operation_type}:no_evaluator",)
        capability_type, evaluator = row
        if capability is None:
            return (f"operation:{requirement.operation_type}:unsupported",)
        if not isinstance(capability, capability_type):
            return (f"operation:{requirement.operation_type}:invalid_capability",)
        return evaluator(requirement, capability, context)


def _powered_ascent(req, cap: PoweredAscentCapability, ctx: OperationEvaluationContext) -> tuple[str, ...]:
    failures: list[str] = []
    if req.delta_v_km_s > cap.max_delta_v_km_s + 1e-9:
        failures.append(f"operation:{req.operation_type}:delta_v:{req.delta_v_km_s:g}/{cap.max_delta_v_km_s:g}")
    if ctx.origin_surface is None:
        failures.append(f"operation:{req.operation_type}:origin_surface_required")
    else:
        gravity, pressure = ctx.origin_surface
        if gravity > cap.max_surface_gravity_m_s2 + 1e-9:
            failures.append(f"operation:{req.operation_type}:gravity:{gravity:g}/{cap.max_surface_gravity_m_s2:g}")
        if pressure > cap.max_surface_pressure_pa + 1e-9:
            failures.append(f"operation:{req.operation_type}:pressure:{pressure:g}/{cap.max_surface_pressure_pa:g}")
    return tuple(failures)


def _spaceflight(req, cap: SpaceflightCapability, ctx: OperationEvaluationContext) -> tuple[str, ...]:
    failures: list[str] = []
    if req.delta_v_km_s > cap.max_delta_v_km_s + 1e-9:
        failures.append(f"operation:{req.operation_type}:delta_v:{req.delta_v_km_s:g}/{cap.max_delta_v_km_s:g}")
    return tuple(failures)


def _landing(req, cap: LandingCapability, ctx: OperationEvaluationContext) -> tuple[str, ...]:
    failures: list[str] = []
    if req.delta_v_km_s > cap.max_delta_v_km_s + 1e-9:
        failures.append(f"operation:{req.operation_type}:delta_v:{req.delta_v_km_s:g}/{cap.max_delta_v_km_s:g}")
    if ctx.destination_surface is None:
        failures.append(f"operation:{req.operation_type}:destination_surface_required")
    else:
        gravity, pressure = ctx.destination_surface
        if gravity > cap.max_surface_gravity_m_s2 + 1e-9:
            failures.append(f"operation:{req.operation_type}:gravity:{gravity:g}/{cap.max_surface_gravity_m_s2:g}")
        if pressure > cap.max_surface_pressure_pa + 1e-9:
            failures.append(f"operation:{req.operation_type}:pressure:{pressure:g}/{cap.max_surface_pressure_pa:g}")
    return tuple(failures)


def _atmospheric_entry(req, cap: AtmosphericEntryCapability, ctx: OperationEvaluationContext) -> tuple[str, ...]:
    if ctx.destination_surface is None:
        return (f"operation:{req.operation_type}:destination_surface_required",)
    _gravity, pressure = ctx.destination_surface
    if pressure > cap.max_surface_pressure_pa + 1e-9:
        return (f"operation:{req.operation_type}:pressure:{pressure:g}/{cap.max_surface_pressure_pa:g}",)
    return ()


def _surface_transport(req, cap: SurfaceTransportCapability, ctx: OperationEvaluationContext) -> tuple[str, ...]:
    if ctx.origin_surface is None or ctx.destination_surface is None or ctx.surface_distance_km is None:
        return (f"operation:{req.operation_type}:same_body_surface_endpoints_required",)
    if cap.max_distance_km is not None and ctx.surface_distance_km > cap.max_distance_km + 1e-9:
        return (
            f"operation:{req.operation_type}:distance:{ctx.surface_distance_km:g}/{cap.max_distance_km:g}",
        )
    return ()


def build_default_operation_registry() -> OperationEvaluatorRegistry:
    registry = OperationEvaluatorRegistry()
    registry.register(POWERED_ASCENT, PoweredAscentCapability, _powered_ascent)
    registry.register(SPACEFLIGHT, SpaceflightCapability, _spaceflight)
    registry.register(LANDING, LandingCapability, _landing)
    registry.register(ATMOSPHERIC_ENTRY, AtmosphericEntryCapability, _atmospheric_entry)
    registry.register(SURFACE_TRANSPORT, SurfaceTransportCapability, _surface_transport)
    return registry
