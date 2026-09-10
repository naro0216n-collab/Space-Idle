from __future__ import annotations

from .domain_extensions import BASE_DOMAIN_EXTENSIONS
from ..contracts import ContractService
from ..facilities import FacilityBook
from ..industry import IndustryService
from ..inventory import InventoryBook
from ..logistics import LogisticsService
from ..maintenance import FacilityMaintenanceService
from ..power import PowerService
from ..projects import ProjectService
from ..research import ResearchService
from ..shared import AccountState
from ..simulation import Simulation
from ..storage import StorageService
from ..survey import ExtractionService, SurveyService
from ..technology import TechnologyState
from ..scientific_exploration import ScientificExplorationService

from ..content import base_ids as ids
from ..content.base_construction import (
    build_construction_providers,
    build_construction_recipes,
    build_construction_resource_providers,
    build_facility_upgrade_recipes,
    sourcing_wait_days,
)
from ..content.base_contracts import build_contract_templates
from ..content.base_facilities import build_facility_definitions, initial_facility_placements, initial_facility_investments
from ..content.base_industry import build_process_specs
from ..content.base_initial_state import configure_initial_inventory
from ..content.base_power import build_power_specs
from ..content.base_progression import (
    build_extraction_specs,
    build_survey_providers,
    build_survey_targets,
    initial_known_deposits,
)
from ..content.base_research import build_research_definitions, build_research_providers
from ..content.base_scientific_exploration import build_scientific_exploration_definitions
from ..content.base_spatial import build_spatial_model
from ..content.base_storage import build_storage_provider_specs
from ..content.base_transport import (
    build_external_transport_services,
    build_route_definitions,
    build_vehicle_definitions,
    initial_vehicle_deployments,
)


def build_base_simulation() -> Simulation:
    """Compose the base-game domain services from content-owned definitions."""
    graph, environment = build_spatial_model()

    facilities = FacilityBook(build_facility_definitions(), environment)
    initial_investments = initial_facility_investments()
    for facility_id, location_id in initial_facility_placements():
        facilities.install(
            facility_id, location_id,
            invested_resources=initial_investments.get(facility_id, {}),
        )

    inventory = InventoryBook()
    configure_initial_inventory(inventory)

    # Money remains an auxiliary settlement balance for explicitly financial
    # boundaries such as commercial transport. Base-game growth is not funded
    # by passive income or automatically offered contracts.
    account = AccountState(1800.0)
    technology = TechnologyState()
    power = PowerService(build_power_specs(), environment)

    logistics = LogisticsService(
        build_route_definitions(), inventory, account, facilities, power,
        technology_state=technology,
    )
    logistics.external_services.update(build_external_transport_services())
    logistics.vehicle_defs.update(build_vehicle_definitions())
    for vehicle_definition_id, count, location_id in initial_vehicle_deployments():
        logistics.add_vehicles(vehicle_definition_id, count, location_id)

    industry = IndustryService(build_process_specs())

    projects = ProjectService(
        recipes=build_construction_recipes(),
        upgrade_recipes=build_facility_upgrade_recipes(),
        construction_providers=build_construction_providers(),
        inventory=inventory,
        facilities=facilities,
        power=power,
        sourcing_wait_days=sourcing_wait_days(),
        technology_state=technology,
        construction_resource_providers=build_construction_resource_providers(),
    )

    storage = StorageService(build_storage_provider_specs(), inventory, facilities)
    maintenance = FacilityMaintenanceService(facilities, inventory)

    research = ResearchService(
        build_research_definitions(), build_research_providers(),
        facilities, inventory, power, technology_state=technology,
    )
    scientific_exploration = ScientificExplorationService(
        build_scientific_exploration_definitions(),
        facilities, inventory, power, logistics, research,
    )
    survey = SurveyService(build_survey_targets(), build_survey_providers(), facilities)
    for location_id, resource_id in initial_known_deposits():
        survey.initialize_known(location_id, resource_id)
    extraction = ExtractionService(build_extraction_specs(), survey)

    # Keep the Contract Domain composed and available for future events,
    # collaboration, or scenario content. Base Game starts with no offers.
    contracts = ContractService(build_contract_templates(), facilities, logistics, power, account)

    sim = Simulation(
        0, account, graph, environment, inventory, facilities, power, storage,
        industry, logistics, projects, technology, contracts, research, survey, extraction,
        scientific_exploration=scientific_exploration, maintenance=maintenance,
    )
    initial_locations = {facility.location_id for facility in facilities.facilities.values()} | set(graph.nodes)
    initial_power = {loc: power.snapshot(loc, facilities, 0) for loc in sorted(initial_locations, key=str)}
    storage.refresh(0, initial_power)
    sim.content_id = "base_game.gameplay.v0.4.5"
    sim.domain_extensions = BASE_DOMAIN_EXTENSIONS
    return sim
