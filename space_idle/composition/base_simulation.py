from __future__ import annotations

from .domain_extensions import BASE_DOMAIN_EXTENSIONS
from ..contracts import ContractService
from ..external_economy import ExternalEconomyState
from ..facilities import FacilityBook
from ..founding import LocationFoundingService
from ..industry import IndustryService
from ..inventory import InventoryBook
from ..logistics import LogisticsService
from ..transport.service import TransportService
from ..maintenance import FacilityMaintenanceService
from ..power import PowerService
from ..projects import ProjectService
from ..research import ResearchService
from ..shared import AccountState, EntityId
from ..simulation import Simulation
from ..storage import StorageService
from ..surface_infrastructure import SurfaceInfrastructureService
from ..survey import ExtractionService, SurveyService
from ..technology import TechnologyState
from ..scientific_exploration import ScientificExplorationService

from ..content import base_ids as ids
from ..content.base_construction import (
    build_construction_providers,
    build_construction_recipes,
    build_construction_resource_providers,
    build_facility_upgrade_recipes,
    build_spatial_development_recipes,
    sourcing_wait_days,
)
from ..content.base_contracts import build_contract_templates
from ..content.base_facilities import build_facility_definitions, initial_facility_placements, initial_facility_investments
from ..content.base_founding import build_founding_packages
from ..content.base_industry import build_process_specs
from ..content.base_initial_state import configure_initial_inventory
from ..content.base_power import build_power_specs
from ..content.base_procurement import build_external_procurement_services
from ..content.base_progression import (
    build_extraction_specs,
    build_survey_providers,
    build_survey_targets,
    initial_known_surface_resource_knowledge,
)
from ..content.base_research import (
    build_experience_contribution_rules, build_research_definitions, build_research_providers,
)
from ..content.base_scientific_exploration import build_scientific_exploration_definitions
from ..content.base_spatial import build_spatial_model
from ..content.base_storage import build_storage_provider_specs
from ..content.base_transport import (
    build_external_transport_services,
    build_route_definitions,
    build_surface_orbit_route_rules,
    build_surface_route_rules,
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

    # Funds are organization-level settlement state. External spending is
    # authorized by explicit policy/allocation; base-game growth is not funded
    # by passive income or automatically offered contracts.
    account = AccountState(1800.0)
    external_economy = ExternalEconomyState(account)
    technology = TechnologyState()
    power = PowerService(build_power_specs(), environment)

    transport = TransportService(
        routes=build_route_definitions(),
        inventory=inventory,
        facilities=facilities,
        power=power,
        surface_route_rules=build_surface_route_rules(),
        surface_orbit_route_rules=build_surface_orbit_route_rules(),
        technology_state=technology,
    )
    transport.external_services.update(build_external_transport_services())
    for service_id in transport.external_services:
        external_economy.register_service(service_id)
    transport.vehicle_defs.update(build_vehicle_definitions())
    transport.synchronize_surface_access_routes()
    for vehicle_definition_id, count, location_id in initial_vehicle_deployments():
        transport.add_fleet_units(vehicle_definition_id, count, location_id)

    logistics = LogisticsService(
        transport=transport,
        inventory=inventory,
        external_economy=external_economy,
        facilities=facilities,
    )
    logistics.procurement_services.update(build_external_procurement_services())
    for service_id in logistics.procurement_services:
        external_economy.register_service(service_id)

    industry = IndustryService(build_process_specs())

    surface_infrastructure = SurfaceInfrastructureService(graph)
    survey = SurveyService(build_survey_targets(), build_survey_providers(), facilities, graph)
    for cell_id, resource_id in initial_known_surface_resource_knowledge():
        survey.initialize_known(cell_id, resource_id)

    projects = ProjectService(
        recipes=build_construction_recipes(),
        upgrade_recipes=build_facility_upgrade_recipes(),
        construction_providers=build_construction_providers(),
        inventory=inventory,
        facilities=facilities,
        power=power,
        sourcing_wait_days=sourcing_wait_days(),
        surface_infrastructure=surface_infrastructure,
        surface_knowledge_level_provider=survey.cell_knowledge_level,
        technology_state=technology,
        construction_resource_providers=build_construction_resource_providers(),
        spatial_recipes=build_spatial_development_recipes(),
        surface_cell_development_recipe_id=ids.SURFACE_CELL_DEVELOPMENT_PROJECT,
    )

    storage = StorageService(build_storage_provider_specs(), inventory, facilities)

    founding = LocationFoundingService(
        build_founding_packages(), facilities, inventory, power, transport, storage,
        surface_knowledge_level_provider=survey.cell_knowledge_level,
    )
    projects.external_surface_cell_claim_provider = lambda cell_id: (
        None if (project := founding.active_project_for_cell(cell_id)) is None else EntityId(project.id)
    )
    founding.external_cell_claim_provider = lambda cell_id: (
        None if (project := projects.active_spatial_project_for_cell(cell_id)) is None else EntityId(project.id)
    )

    maintenance = FacilityMaintenanceService(facilities, inventory)

    research = ResearchService(
        build_research_definitions(), build_research_providers(),
        facilities, inventory, power, technology_state=technology,
        experience_rules=build_experience_contribution_rules(),
    )
    scientific_exploration = ScientificExplorationService(
        build_scientific_exploration_definitions(),
        facilities, inventory, power, transport, research,
    )
    extraction = ExtractionService(build_extraction_specs(), graph, surface_infrastructure)

    # Keep the Contract Domain composed and available for future events,
    # collaboration, or scenario content. Base Game starts with no offers.
    contracts = ContractService(build_contract_templates(), facilities, power, account)

    sim = Simulation(
        day=0, external_economy=external_economy, graph=graph, environment=environment, inventory=inventory,
        facilities=facilities, power=power, storage=storage, industry=industry, transport=transport, logistics=logistics,
        projects=projects, technology=technology, founding=founding, contracts=contracts,
        research=research, survey=survey, extraction=extraction,
        scientific_exploration=scientific_exploration, maintenance=maintenance,
        surface_infrastructure=surface_infrastructure,
    )
    sim.refresh_storage()
    sim.content_id = "base_game.gameplay.v0.4.5"
    sim.domain_extensions = BASE_DOMAIN_EXTENSIONS
    return sim
