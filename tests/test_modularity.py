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


def test_logistics_consumes_transport_projection_instead_of_transport_state_containers():
    tree = ast.parse(
        (PACKAGE / "logistics_flow.py").read_text(encoding="utf-8"),
        filename="logistics_flow.py",
    )
    forbidden_state = {"transport_allocations", "vehicle_defs", "routes", "external_services"}
    direct_state_reads = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in forbidden_state:
            continue
        owner = node.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr == "transport"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            direct_state_reads.append(node.attr)
    assert direct_state_reads == []


def test_founding_and_exploration_use_transport_fleet_facade():
    forbidden_state = {"vehicle_defs", "fleet_reservations"}
    violations: list[tuple[str, str]] = []
    for filename in (
        "founding.py",
        "founding_domain.py",
        "scientific_exploration.py",
        "scientific_exploration_domain.py",
    ):
        tree = ast.parse(
            (PACKAGE / filename).read_text(encoding="utf-8"),
            filename=filename,
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr not in forbidden_state:
                continue
            owner = node.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == "transport"):
                continue
            root = owner.value
            if isinstance(root, ast.Name) and root.id in {"self", "sim"}:
                violations.append((filename, node.attr))
    assert violations == []


def test_application_reads_transport_through_public_facade():
    authoritative_state = {
        "vehicle_defs",
        "routes",
        "external_services",
        "fleet_pools",
        "fleet_reservations",
        "transport_allocations",
        "fleet_relocations",
        "fleet_releases",
        "vehicle_production_projects",
    }
    violations: list[tuple[str, str]] = []
    for path in sorted(PACKAGE.glob("application*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == "transport"):
                continue
            if node.attr in authoritative_state or node.attr.startswith("_"):
                violations.append((path.name, node.attr))
    assert violations == []


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
