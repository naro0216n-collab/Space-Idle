from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AcceptContract: contract_id: str
@dataclass(frozen=True)
class DispatchContractCargo:
    contract_id: str; path: tuple[str, ...] | None = None; route_modes: tuple[tuple[str, str], ...] = ()
@dataclass(frozen=True)
class DeclineContract: contract_id: str
