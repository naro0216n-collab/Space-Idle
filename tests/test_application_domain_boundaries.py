from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "space_idle"


def test_construction_owns_demand_without_transport_or_account_state_dependencies():
    from space_idle.projects import ProjectService

    fields = ProjectService.__dataclass_fields__
    assert "logistics" not in fields
    assert "account" not in fields

    for path in (PACKAGE / "construction").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from ..logistics" not in source
        assert "from .logistics" not in source



def test_transport_and_logistics_own_disjoint_authoritative_state():
    from space_idle.logistics import LogisticsService
    from space_idle.transport.service import TransportService

    logistics_fields = set(LogisticsService.__dataclass_fields__)
    transport_fields = set(TransportService.__dataclass_fields__)

    assert {"lanes", "cargo_flows", "transport"}.issubset(logistics_fields)
    assert not {
        "fleet_pools", "fleet_reservations", "transport_allocations",
        "fleet_relocations", "fleet_releases", "vehicle_production_projects",
        "vehicle_defs", "routes", "external_services",
    } & logistics_fields

    assert {
        "fleet_pools", "fleet_reservations", "transport_allocations",
        "fleet_relocations", "fleet_releases", "vehicle_production_projects",
        "vehicle_defs", "routes", "external_services",
    }.issubset(transport_fields)
    assert not {"lanes", "cargo_flows"} & transport_fields


def test_application_reads_logistics_mutable_state_through_public_snapshots():
    forbidden_state = {"lanes", "cargo_flows", "procurement_deliveries"}
    violations: list[tuple[str, str]] = []
    for path in sorted(PACKAGE.glob("application*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr not in forbidden_state:
                continue
            owner = node.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == "logistics"):
                continue
            violations.append((path.name, node.attr))
    assert violations == []
