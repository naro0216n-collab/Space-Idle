from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
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


def _self_method_dependency_graph(directory: Path) -> dict[str, set[str]]:
    """Map implementation module -> modules whose private self methods it calls."""
    owners: dict[str, str] = {}
    parsed: dict[str, ast.AST] = {}
    for path in directory.glob("*.py"):
        if path.name in {"__init__.py", "models.py", "domain.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = path.stem
        parsed[module] = tree
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_"):
                owners.setdefault(node.name, module)

    graph = {module: set() for module in parsed}
    for module, tree in parsed.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            if isinstance(value, ast.Name) and value.id == "self":
                owner = owners.get(node.func.attr)
                if owner is not None and owner != module:
                    graph[module].add(owner)
    return graph


def _assert_acyclic(graph: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        assert node not in visiting, f"cyclic implementation dependency at {node}: {graph}"
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def test_cross_cutting_state_and_validation_are_owned_by_registered_domains():
    from space_idle.composition.domain_extensions import BASE_DOMAIN_EXTENSIONS
    from space_idle.domain import validate_extension_registry

    validate_extension_registry(BASE_DOMAIN_EXTENSIONS)
    names = [extension.name for extension in BASE_DOMAIN_EXTENSIONS]
    assert len(names) == len(set(names))
    assert {
        "core", "spatial", "technology", "facilities", "inventory", "storage",
        "production", "logistics", "construction", "contracts", "research",
        "survey", "extraction",
    }.issubset(names)

    codec_keys = [
        extension.state_codec.key
        for extension in BASE_DOMAIN_EXTENSIONS
        if extension.state_codec is not None
    ]
    assert len(codec_keys) == len(set(codec_keys))
    assert {"facilities", "inventory", "industry", "logistics", "projects", "research", "survey"}.issubset(codec_keys)
    assert sum(extension.configuration_validator is not None for extension in BASE_DOMAIN_EXTENSIONS) > 1
    assert sum(extension.runtime_validator is not None for extension in BASE_DOMAIN_EXTENSIONS) > 1


def test_major_mutable_domain_states_are_owned_enums_not_distributed_string_sets():
    from space_idle.contracts import ContractStatus
    from space_idle.projects import ProjectStatus
    from space_idle.research import ResearchPhase
    from space_idle.logistics import FleetReservationKind, TransportControlMode
    from space_idle.transport import CargoFlowStatus
    from space_idle.transport.production import VehicleProductionPhase

    for state_type in (
        ContractStatus, ProjectStatus, ResearchPhase, FleetReservationKind,
        TransportControlMode, CargoFlowStatus, VehicleProductionPhase,
    ):
        assert issubclass(state_type, Enum)
        assert issubclass(state_type, str)


def test_public_domain_facades_compose_focused_implementations():
    from space_idle.application_query_projectors import ApplicationQueryMixin
    from space_idle.application_command_handlers import ApplicationCommandMixin
    from space_idle.industry import IndustryService
    from space_idle.logistics import LogisticsService
    from space_idle.projects import ProjectService
    from space_idle.research import ResearchService

    def bases(cls):
        return {base.__name__ for base in cls.__mro__[1:]}

    assert {
        "TransportCompatibilityMixin", "FleetAllocationMixin", "TransportLaneMixin",
        "SteadyLogisticsMixin", "VehicleProductionMixin",
    }.issubset(bases(LogisticsService))
    assert not {"TransportPlanningMixin", "TransportExecutionMixin", "FleetManagementMixin"} & bases(LogisticsService)
    assert {"ConstructionRulesMixin", "ConstructionPlanningMixin", "ConstructionProcurementMixin", "ConstructionExecutionMixin"}.issubset(bases(ProjectService))
    assert {"ProcessSelectionMixin", "IndustryPlanningMixin", "IndustryExecutionMixin"}.issubset(bases(IndustryService))
    assert {"ResearchWorkflowMixin", "ResearchCapacityMixin", "ResearchExecutionMixin"}.issubset(bases(ResearchService))
    assert {"LocationProjectorMixin", "LogisticsProjectorMixin", "ProgressionProjectorMixin"}.issubset(bases(ApplicationQueryMixin))
    assert {"ConstructionCommandHandlerMixin", "ProgressionCommandHandlerMixin", "TransportCommandHandlerMixin"}.issubset(bases(ApplicationCommandMixin))


def test_content_composition_and_architecture_stress_modules_have_unambiguous_ownership():
    content = PACKAGE / "content"
    composition = PACKAGE / "composition"
    assert not (PACKAGE / "missions.py").exists()
    assert (PACKAGE / "mission_stress.py").exists()
    for filename in (
        "base_ids.py", "base_requirements.py", "base_spatial.py", "base_catalog.py",
        "base_facilities.py", "base_transport.py", "base_construction.py",
        "base_industry.py", "base_progression.py", "base_game.py",
    ):
        assert (content / filename).exists()
    assert (composition / "base_simulation.py").exists()
    assert (composition / "domain_extensions.py").exists()
    assert "GameApplication" not in (content / "base_game.py").read_text(encoding="utf-8")


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


def test_internal_modules_use_explicit_import_contracts():
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names), f"star import in {path.relative_to(PACKAGE)}"


def test_cross_file_mixin_dependencies_remain_acyclic():
    for package_name in ("transport", "construction", "production"):
        graph = _self_method_dependency_graph(PACKAGE / package_name)
        _assert_acyclic(graph)


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


def test_create_logistics_lane_preserves_resource_agnostic_path_policy_across_application_boundary():
    from space_idle import CreateLogisticsLane, GetLogistics, build_game_application

    app = build_game_application()
    result = app.execute(CreateLogisticsLane(
        source_id="base.node.earth_surface",
        destination_id="base.node.low_earth_orbit",
        requested_capacity_t_per_day=0.25,
        path_policy="lowest_cost",
    ))
    assert result.created_id is not None
    row = next(lane for lane in app.query(GetLogistics()).lanes if lane.id == result.created_id)
    assert row.path_policy == "lowest_cost"
    lane = app._simulation.logistics.lanes[next(
        lane_id for lane_id in app._simulation.logistics.lanes if str(lane_id) == result.created_id
    )]
    assert not hasattr(lane, "resource_id")
    assert not hasattr(lane, "target_stock_t")
    assert not hasattr(lane, "batch_t")
