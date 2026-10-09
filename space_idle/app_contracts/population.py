from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetPopulationTarget:
    operational_node_id: str
    desired_count: int

    def __post_init__(self) -> None:
        if not self.operational_node_id or isinstance(self.desired_count, bool) or not isinstance(self.desired_count, int) or self.desired_count < 0:
            raise ValueError('population target requires an existing node and nonnegative integer')


@dataclass(frozen=True)
class ClearPopulationTarget:
    operational_node_id: str

    def __post_init__(self) -> None:
        if not self.operational_node_id:
            raise ValueError('population target node required')
