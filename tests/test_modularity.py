from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "space_idle"


def _module_import_targets(path: Path) -> set[str]:
    """Return normalized relative import targets for architecture assertions."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_parts = list(path.relative_to(PACKAGE).with_suffix("").parts)
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_parts[:-1]
                trim = max(0, node.level - 1)
                if trim:
                    base = base[:-trim]
                if node.module:
                    base += node.module.split(".")
                targets.add("space_idle." + ".".join(base))
            elif node.module:
                targets.add(node.module)
    return targets


def test_domain_authoritative_state_is_not_read_directly_across_domain_boundaries():
    from space_idle.logistics import LogisticsService
    from space_idle.transport.service import TransportService

    authoritative_state = {
        "transport": {
            "vehicle_defs",
            "fleet_pools",
            "fleet_reservations",
            "transport_allocations",
            "fleet_relocations",
            "fleet_releases",
            "vehicle_production_projects",
        },
        "logistics": {
            "target_stocks", "supply_policies", "cargo_flows", "arrival_waiting",
        },
    }
    service_fields = {
        "transport": set(TransportService.__dataclass_fields__),
        "logistics": set(LogisticsService.__dataclass_fields__),
    }

    for domain, fields in authoritative_state.items():
        assert fields <= service_fields[domain]
        for other_domain, other_fields in service_fields.items():
            if other_domain != domain:
                assert not fields & other_fields

    violations: list[tuple[str, str]] = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value
            if not isinstance(owner, ast.Attribute):
                continue
            domain = owner.attr
            fields = authoritative_state.get(domain)
            if fields is None or node.attr not in fields:
                continue
            if domain == "transport" and rel.parts[0] == "transport":
                continue
            if domain == "logistics" and rel.name.startswith("logistics"):
                continue
            violations.append((str(rel), f"{domain}.{node.attr}"))

    assert violations == []

    construction_files = [PACKAGE / "projects.py", *(PACKAGE / "construction").glob("*.py")]
    for path in construction_files:
        targets = _module_import_targets(path)
        offenders = sorted(
            target
            for target in targets
            if target.startswith(
                (
                    "space_idle.logistics",
                    "space_idle.transport",
                )
            )
        )
        assert not offenders, (
            f"{path.relative_to(PACKAGE)} bypasses Supply Requirement / Execution Claim boundary: {offenders}"
        )


def test_layer_dependency_direction_is_enforced():
    """Core/domain code cannot acquire inward dependencies on outer layers."""
    forbidden_outer = (
        "space_idle.application", "space_idle.app_contracts", "space_idle.content",
        "space_idle.composition", "space_idle.bootstrap", "space_idle.persistence", "space_idle.api",
    )

    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        if path.name == "__init__.py":
            continue
        parts = rel.parts
        name = rel.name

        if parts[0] in {"content", "composition", "app_contracts", "api"}:
            continue
        if name == "bootstrap.py" or name == "persistence.py" or name.startswith("application"):
            continue

        targets = _module_import_targets(path)
        offenders = sorted(target for target in targets if target.startswith(forbidden_outer))
        assert not offenders, f"{rel} imports outer layer(s): {offenders}"

    for path in (PACKAGE / "content").glob("*.py"):
        targets = _module_import_targets(path)
        offenders = sorted(
            target for target in targets
            if target.startswith(("space_idle.application", "space_idle.app_contracts", "space_idle.composition", "space_idle.bootstrap", "space_idle.persistence", "space_idle.api"))
        )
        assert not offenders, f"{path.relative_to(PACKAGE)} imports outer layer(s): {offenders}"

    for path in (PACKAGE / "composition").glob("*.py"):
        targets = _module_import_targets(path)
        offenders = sorted(
            target for target in targets
            if target.startswith(("space_idle.application", "space_idle.app_contracts", "space_idle.bootstrap", "space_idle.persistence", "space_idle.api"))
        )
        assert not offenders, f"{path.relative_to(PACKAGE)} imports outer layer(s): {offenders}"

    application_files = list(PACKAGE.glob("application*.py")) + list((PACKAGE / "app_contracts").glob("*.py"))
    for path in application_files:
        targets = _module_import_targets(path)
        offenders = sorted(
            target for target in targets
            if target.startswith(("space_idle.content", "space_idle.composition", "space_idle.bootstrap", "space_idle.persistence", "space_idle.api"))
        )
        assert not offenders, f"{path.relative_to(PACKAGE)} imports concrete composition/content: {offenders}"

    for path in (PACKAGE / "api").glob("*.py"):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        targets = _module_import_targets(path)
        offenders = sorted(
            target for target in targets
            if target.startswith(("space_idle.content", "space_idle.composition", "space_idle.bootstrap"))
        )
        assert not offenders, f"{path.relative_to(PACKAGE)} imports concrete composition/content: {offenders}"


def test_transport_operation_extension_does_not_require_central_enum_change():
    from space_idle.transport.models import TransportOperationRequirement
    from space_idle.transport.operations import OperationEvaluationContext, OperationEvaluatorRegistry

    @dataclass(frozen=True)
    class TestCapability:
        limit: float
        operation_type: str = "test.custom_operation"

    registry = OperationEvaluatorRegistry()

    def evaluator(requirement, capability, context):
        assert context.transit_days == 7
        return () if requirement.delta_v_km_s <= capability.limit else ("limit",)

    registry.register("test.custom_operation", TestCapability, evaluator)
    requirement = TransportOperationRequirement("test.custom_operation", 2.0)
    context = OperationEvaluationContext(7, None, None)
    assert registry.evaluate(requirement, TestCapability(3.0), context) == ()
    assert registry.evaluate(requirement, TestCapability(1.0), context) == ("limit",)


def test_allocation_pool_provider_extension_does_not_require_central_enum_change():
    from space_idle import build_game_application
    from space_idle.domain import DomainExtension
    from space_idle.execution_requirements import pool_constraint

    sim = build_game_application()._simulation
    custom_key = pool_constraint("test.custom_pool", scope_id="test")

    @dataclass
    class TestPoolProvider:
        capacity: float

        def allocation_pool_capacities(self, day: int):
            return {custom_key: self.capacity}

    provider = TestPoolProvider(7.0)
    sim.domain_extensions += (
        DomainExtension(
            "test_custom_pool",
            allocation_pool_provider=lambda _sim: provider,
        ),
    )

    assert provider in sim.allocation_pool_providers()
    assert sim.allocation_pool_capacities()[custom_key] == 7.0
