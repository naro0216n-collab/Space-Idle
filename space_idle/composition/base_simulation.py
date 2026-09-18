from __future__ import annotations

from .domain_extensions import BASE_DOMAIN_EXTENSIONS
from ..contracts import ContractService
from ..market import FundsState, MarketService
from ..facilities import FacilityBook
from ..facility_lifecycle import FacilityLifecycleRegistry
from ..founding import OperationalNodeFoundingService
from ..industry import IndustryService
from ..inventory import InventoryBook
from ..logistics import LogisticsService
from ..transport.service import TransportService
from ..maintenance import FacilityMaintenanceService
from ..power import PowerService
from ..projects import ProjectService
from ..research import ResearchService
from ..service_capacity import ServiceCapacityRegistry
from ..simulation import Simulation
from ..storage import StorageService
from ..surface_infrastructure import SurfaceInfrastructureService
from ..spatial_claims import SurfaceCellClaimRegistry
from ..survey import ExtractionService, SurveyService
from ..technology import TechnologyState
from ..scientific_exploration import ScientificExplorationService
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..catalog import GameCatalog

from ..content import base_ids as ids
from ..content.base_construction import (
    build_construction_providers,
    build_construction_recipes,
    build_construction_resource_providers,
    build_facility_upgrade_recipes,
    build_facility_decommission_recipes,
    build_spatial_development_recipes,
    procurement_wait_days,
)
from ..content.base_contracts import build_contract_templates
from ..content.base_facilities import build_facility_definitions
from ..content.base_founding import build_deployment_recipes
from ..content.base_industry import build_process_specs
from ..content.base_power import build_power_specs
from ..content.base_market import build_market_provider_definitions
from ..content.base_progression import (
    build_extraction_specs,
    build_survey_providers,
    build_survey_targets,
)
from ..content.base_research import (
    build_experience_contribution_rules, build_research_definitions, build_research_providers,
)
from ..content.base_scientific_exploration import build_scientific_exploration_definitions
from ..content.base_spatial import BASE_WORLD_DEFINITION_ID, build_world_definition
from ..content.base_storage import build_storage_provider_specs
from ..content.base_transport import (
    build_spaceflight_movement_rules,
    build_surface_access_movement_rules,
    build_surface_movement_rules,
    build_vehicle_definitions,
)


def build_base_simulation(catalog: GameCatalog) -> Simulation:
    """Compose static base-game definitions with empty authoritative runtime State."""
    graph, environment = build_world_definition()

    facility_definitions = build_facility_definitions()
    facilities = FacilityBook(facility_definitions, environment)
    service_capacity_registry = ServiceCapacityRegistry()

    inventory = InventoryBook(resource_definitions=catalog.resources)

    # Provider offers are static Content. Funds, provider availability and
    # Market Interfaces are Scenario-owned runtime State.
    market = MarketService(FundsState(0.0))
    for provider in build_market_provider_definitions().values():
        market.register_provider_definition(provider)
    technology = TechnologyState()
    power = PowerService(build_power_specs(), environment)

    transport = TransportService(
        inventory=inventory,
        facilities=facilities,
        power=power,
        service_capacity_registry=service_capacity_registry,
        surface_movement_rules=build_surface_movement_rules(),
        surface_access_movement_rules=build_surface_access_movement_rules(),
        spaceflight_movement_rules=build_spaceflight_movement_rules(),
        technology_state=technology,
    )
    transport.vehicle_defs.update(build_vehicle_definitions())

    logistics = LogisticsService(
        transport=transport,
        inventory=inventory,
        facilities=facilities,
    )

    industry = IndustryService(build_process_specs())

    surface_infrastructure = SurfaceInfrastructureService(
        graph, facilities, service_capacity_registry
    )
    survey = SurveyService(build_survey_targets(), build_survey_providers(), facilities, graph, transport)

    storage = StorageService(build_storage_provider_specs(), inventory, facilities)

    facility_lifecycle_registry = FacilityLifecycleRegistry()
    facility_lifecycle_registry.register_blocker_provider("transport", transport)
    facility_lifecycle_registry.register_blocker_provider("storage", storage)

    surface_cell_claim_registry = SurfaceCellClaimRegistry()

    projects = ProjectService(
        recipes=build_construction_recipes(),
        upgrade_recipes=build_facility_upgrade_recipes(),
        decommission_recipes=build_facility_decommission_recipes(facility_definitions),
        construction_providers=build_construction_providers(),
        inventory=inventory,
        facilities=facilities,
        power=power,
        service_capacity_registry=service_capacity_registry,
        procurement_wait_days=procurement_wait_days(),
        surface_infrastructure=surface_infrastructure,
        knowledge_requirement_failures=survey.knowledge_requirement_failures,
        technology_state=technology,
        construction_resource_providers=build_construction_resource_providers(),
        spatial_recipes=build_spatial_development_recipes(),
        surface_cell_development_recipe_id=ids.SURFACE_CELL_DEVELOPMENT_PROJECT,
        surface_cell_claim_registry=surface_cell_claim_registry,
        facility_lifecycle_registry=facility_lifecycle_registry,
    )

    founding = OperationalNodeFoundingService(
        build_deployment_recipes(), facilities, inventory, power, transport, storage,
        service_capacity_registry,
        knowledge_requirement_failures=survey.knowledge_requirement_failures,
        surface_cell_claim_registry=surface_cell_claim_registry,
    )
    maintenance = FacilityMaintenanceService(facilities, inventory)

    research = ResearchService(
        build_research_definitions(), build_research_providers(),
        facilities, inventory, power, service_capacity_registry, transport, technology_state=technology,
        experience_rules=build_experience_contribution_rules(),
    )
    scientific_exploration = ScientificExplorationService(
        build_scientific_exploration_definitions(),
        facilities, inventory, power, transport, research, service_capacity_registry,
    )
    transport.register_fleet_commitment_owner_resolver(
        "founding", lambda owner_id: owner_id in founding.projects
    )
    transport.register_fleet_commitment_owner_resolver(
        "survey_provider_assignment", lambda owner_id: owner_id in survey.provider_assignments
    )
    transport.register_fleet_commitment_owner_resolver(
        "scientific_exploration", lambda owner_id: owner_id in scientific_exploration.campaigns
    )
    transport.register_fleet_commitment_owner_resolver(
        "research_provider_assignment", lambda owner_id: owner_id in research.provider_assignments
    )
    logistics.register_supply_owner_resolver(
        "project", lambda owner_id: owner_id in projects.projects
    )
    logistics.register_supply_owner_resolver(
        "founding", lambda owner_id: owner_id in founding.projects
    )
    logistics.register_supply_owner_resolver(
        "facility_maintenance", lambda owner_id: owner_id in facilities.facilities
    )
    logistics.register_supply_owner_resolver(
        "vehicle_production", lambda owner_id: owner_id in transport.vehicle_production_projects
    )
    logistics.register_supply_owner_resolver(
        "fleet_relocation", lambda owner_id: owner_id in transport.fleet_relocations
    )
    logistics.register_supply_owner_resolver(
        "market_sell", lambda owner_id: owner_id in market.orders
    )

    def industry_owner_exists(owner_id: EntityId) -> bool:
        prefix = "industry.site:"
        value = str(owner_id)
        return value.startswith(prefix) and graph.has_operational_node(
            SpatialNodeId(value[len(prefix):])
        )

    def research_owner_exists(owner_id: EntityId) -> bool:
        prefix = "research:"
        value = str(owner_id)
        return value.startswith(prefix) and DefinitionId(value[len(prefix):]) in research.active

    def exploration_owner_exists(owner_id: EntityId) -> bool:
        prefix = "scientific_exploration:"
        value = str(owner_id)
        return (
            value.startswith(prefix)
            and DefinitionId(value[len(prefix):]) in scientific_exploration.campaigns
        )

    logistics.register_supply_owner_resolver("industry", industry_owner_exists)
    logistics.register_supply_owner_resolver("research", research_owner_exists)
    logistics.register_supply_owner_resolver(
        "scientific_exploration", exploration_owner_exists
    )
    extraction = ExtractionService(build_extraction_specs(), graph, environment, surface_infrastructure)

    # Keep the Contract Domain composed and available for future events,
    # collaboration, or scenario content. Base Game starts with no offers.
    contracts = ContractService(
        build_contract_templates(), facilities, power, service_capacity_registry
    )

    sim = Simulation(
        day=0, market=market, graph=graph, environment=environment, inventory=inventory,
        facilities=facilities, power=power, storage=storage, industry=industry, transport=transport, logistics=logistics,
        projects=projects, technology=technology, founding=founding, contracts=contracts,
        service_capacity_registry=service_capacity_registry,
        research=research, survey=survey, extraction=extraction,
        scientific_exploration=scientific_exploration, maintenance=maintenance,
        surface_infrastructure=surface_infrastructure,
    )
    sim.content_id = "base_game.gameplay.v0.4.5"
    sim.world_definition_id = BASE_WORLD_DEFINITION_ID
    sim.domain_extensions = BASE_DOMAIN_EXTENSIONS
    service_capacity_registry.bind_provider_source(sim.service_capacity_providers)
    return sim
