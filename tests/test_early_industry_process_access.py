"""Early material processing is a real Application production option, not a
backdoor into later production methods sharing the same resource family.
"""

from __future__ import annotations

from space_idle.app_contracts.queries import GetBuildOptions, GetCatalog
from space_idle.balance.application_inputs import collect_application_inputs
from space_idle.bootstrap import build_game_application


def test_early_metal_and_ceramic_chain_preserves_physical_process_boundaries():
    app = build_game_application()
    catalog = app.query(GetCatalog())
    facilities = {row.id: row for row in catalog.facilities}
    processes = {row.id: row for row in catalog.processes}
    build_options = {row.facility_definition_id: row
                     for row in app.query(GetBuildOptions('base.location.earth_industrial')).items}

    # The construction/materials stage needs a finite, researched processing
    # facility before later high-yield metallurgy/sintering is available.
    pairs = (
        ('planned.facility.basic_billet_furnace', 'planned.process.earth_primary_billet_casting',
         'base.process.metallurgy'),
        ('planned.facility.basic_ceramics_kiln', 'planned.process.earth_kiln_ceramics',
         'base.process.mineral_sintering'),
    )
    for facility_id, early_process_id, mature_process_id in pairs:
        option = build_options[facility_id]
        assert facilities[facility_id].design is not None
        assert facilities[facility_id].design.prerequisites
        assert any(row.kind == 'technology' for row in option.blockers)
        assert {row.process_id for row in option.process_options} == {early_process_id}
        assert processes[early_process_id].provider_facilities == (facility_id,)
        assert facility_id not in processes[mature_process_id].provider_facilities
        assert option.process_options[0].input_rates_per_day
        assert option.process_options[0].output_rates_per_day

    # The balance CLI only receives the same registered Application projection.
    derived = collect_application_inputs(app)
    for facility_id, early_process_id, mature_process_id in pairs:
        assert derived['processes'][early_process_id]['provider_facilities'] == [facility_id]
        assert facility_id not in derived['processes'][mature_process_id]['provider_facilities']
