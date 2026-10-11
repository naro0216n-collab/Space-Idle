from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PassengerDispatchOptionRow:
    mode: str
    vehicle_definition_id: str
    transport_allocation_ids: tuple[str, ...]
    movement_path: tuple[str, ...]
    units: int
    travel_days: int
    dispatchable_people: int
    waiting_people: int
    passenger_payload_t: float
    resources: tuple[tuple[str, str, float], ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class PassengerTransferPreviewView:
    origin_node_id: str
    destination_node_id: str
    requested_count: int
    available_source_people: int
    destination_housing_spare: int
    destination_life_support_receivable: int
    options: tuple[PassengerDispatchOptionRow, ...]
    external_sources: tuple[tuple[str, int, int, int], ...] = ()
    origin_target_deficit_after_requested_transfer: int | None = None


@dataclass(frozen=True)
class PassengerCargoHoldView:
    owner_ref: str
    physical_node_id: str | None
    resources: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class PassengerTransferRow:
    id: str
    origin_node_id: str
    destination_node_id: str
    requested_count: int
    pending_count: int
    transit_count: int
    delivered_count: int
    cancelled_count: int
    deceased_count: int
    status: str
    source_external_provider_id: str | None
    capacity_mode: str | None
    priority: int
    blockers: tuple[str, ...]
    cargo_holds: tuple[PassengerCargoHoldView, ...] = ()


@dataclass(frozen=True)
class PassengerTransfersView:
    items: tuple[PassengerTransferRow, ...]
