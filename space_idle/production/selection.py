from __future__ import annotations

from ..facilities import FacilityBook, FacilityState
from ..inventory import InventoryBook
from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId
from .models import ProcessSpec, ProcessSnapshot


class ProcessSelectionMixin:
    def compatible_processes(self, facility_def_id: DefinitionId) -> tuple[ProcessSpec, ...]:
        return tuple(process for process in self.processes.values() if process.facility_def_id == facility_def_id)

    def process_for(self, facility: FacilityState) -> ProcessSpec | None:
        compatible = self.compatible_processes(facility.definition_id)
        if not compatible:
            return None
        selected = self.selected_process_by_facility.get(facility.id)
        if selected is not None:
            process = self.processes.get(selected)
            if process is None or process.facility_def_id != facility.definition_id:
                raise RuntimeError("selected process is incompatible with facility")
            return process
        # A single compatible recipe needs no per-instance state. If more are
        # added later, explicit player selection is required rather than relying
        # on definition/registration order.
        if len(compatible) == 1:
            return compatible[0]
        return None

    def set_process(self, facility: FacilityState, process_id: DefinitionId) -> None:
        process = self.processes[process_id]
        if process.facility_def_id != facility.definition_id:
            raise ValueError("process is incompatible with facility")
        self.selected_process_by_facility[facility.id] = process_id
