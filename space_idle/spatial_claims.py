from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .shared import EntityId, SurfaceCellId


@dataclass(frozen=True, order=True)
class SurfaceCellClaim:
    """Derived exclusive-use claim over one Surface Cell.

    Claims are projections of authoritative Domain state.  They are not saved and
    do not transfer ownership of the underlying Project/Operation state to this
    registry.
    """

    cell_id: SurfaceCellId
    claimant_kind: str
    claimant_id: EntityId
    purpose: str


class SurfaceCellClaimProvider(Protocol):
    def surface_cell_claims(self) -> tuple[SurfaceCellClaim, ...]: ...


@dataclass
class SurfaceCellClaimRegistry:
    """Aggregate active Surface Cell claims without pairwise Domain wiring."""

    _providers: list[SurfaceCellClaimProvider] = field(default_factory=list, repr=False)

    def register(self, provider: SurfaceCellClaimProvider) -> None:
        if any(existing is provider for existing in self._providers):
            return
        self._providers.append(provider)

    def claims_for(
        self,
        cell_id: SurfaceCellId,
        *,
        exclude: tuple[str, EntityId] | None = None,
    ) -> tuple[SurfaceCellClaim, ...]:
        rows: list[SurfaceCellClaim] = []
        for provider in self._providers:
            for claim in provider.surface_cell_claims():
                if claim.cell_id != cell_id:
                    continue
                if exclude is not None and (
                    claim.claimant_kind,
                    claim.claimant_id,
                ) == exclude:
                    continue
                rows.append(claim)
        return tuple(sorted(set(rows)))
