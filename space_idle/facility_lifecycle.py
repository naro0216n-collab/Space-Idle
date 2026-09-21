from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .shared import EntityId


@dataclass(frozen=True, order=True)
class FacilityLifecycleBlocker:
    """A durable cross-domain commitment that prevents Facility removal."""

    code: str
    detail: str


class FacilityDecommissionBlockerProvider(Protocol):
    def facility_decommission_blockers(
        self, facility_id: EntityId
    ) -> tuple[FacilityLifecycleBlocker, ...]: ...


class FacilityReferenceReleaser(Protocol):
    def release_facility_reference(self, facility_id: EntityId) -> None: ...


@dataclass
class FacilityLifecycleRegistry:
    """Cross-domain Facility lifecycle participation without pairwise wiring.

    Providers keep authoritative state in their own Domains.  This registry is
    composition-time wiring only and is deliberately not persisted.
    """

    _blocker_providers: dict[str, FacilityDecommissionBlockerProvider] = field(
        default_factory=dict, repr=False
    )
    _reference_releasers: dict[str, FacilityReferenceReleaser] = field(
        default_factory=dict, repr=False
    )

    def register_blocker_provider(
        self, participant_id: str, provider: FacilityDecommissionBlockerProvider
    ) -> None:
        existing = self._blocker_providers.get(participant_id)
        if existing is not None and existing is not provider:
            raise ValueError(f"facility lifecycle blocker provider already registered: {participant_id}")
        self._blocker_providers[participant_id] = provider

    def register_reference_releaser(
        self, participant_id: str, releaser: FacilityReferenceReleaser
    ) -> None:
        existing = self._reference_releasers.get(participant_id)
        if existing is not None and existing is not releaser:
            raise ValueError(f"facility lifecycle reference releaser already registered: {participant_id}")
        self._reference_releasers[participant_id] = releaser

    def decommission_blockers(
        self, facility_id: EntityId
    ) -> tuple[FacilityLifecycleBlocker, ...]:
        blockers = {
            blocker
            for participant_id in sorted(self._blocker_providers)
            for blocker in self._blocker_providers[participant_id].facility_decommission_blockers(
                facility_id
            )
        }
        return tuple(sorted(blockers))

    def release_references(self, facility_id: EntityId) -> None:
        for participant_id in sorted(self._reference_releasers):
            self._reference_releasers[participant_id].release_facility_reference(facility_id)
