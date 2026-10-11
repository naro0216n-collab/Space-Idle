from __future__ import annotations

from ..facilities import FacilityState
from ..shared import DefinitionId
from .models import ProcessSpec


class ProcessSelectionMixin:
    def missing_process_technologies(self, process: ProcessSpec) -> tuple[DefinitionId, ...]:
        return self.technology_state.missing(process.prerequisite_technologies)

    def compatible_processes(self, facility_def_id: DefinitionId) -> tuple[ProcessSpec, ...]:
        """Content-defined interface compatibility, independent of Facility identity."""
        definition = self.facility_defs[facility_def_id]
        capabilities = frozenset(supply.id for supply in definition.capability_supplies)
        return tuple(sorted((
            process for process in self.processes.values()
            if process.required_capabilities <= capabilities
        ), key=lambda process: str(process.id)))

    def process_for(self, facility: FacilityState) -> ProcessSpec | None:
        compatible = self.compatible_processes(facility.definition_id)
        if not compatible:
            return None
        selected = facility.selected_process_id
        if selected is not None:
            process = self.processes.get(selected)
            if process is None or process not in compatible:
                raise RuntimeError("selected process is incompatible with facility")
            return process
        # Single candidate needs no saved selection; multiple candidates require intent.
        if len(compatible) == 1:
            return compatible[0]
        return None

    def set_process(self, facility: FacilityState, process_id: DefinitionId) -> None:
        if process_id not in {row.id for row in self.compatible_processes(facility.definition_id)}:
            raise ValueError("process is incompatible with facility")
        missing = self.missing_process_technologies(self.processes[process_id])
        if missing:
            raise ValueError("process technology requirements not met: " + ", ".join(map(str, missing)))
        facility.selected_process_id = process_id
