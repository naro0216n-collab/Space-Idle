"""Physical fixed transport methods unlocked by late-stage infrastructure.

All values are content coefficients. They do not create free Fleet or Cargo:
Transport owns the selected link, Logistics owns inventory movement, and
Facility Service/Power/maintenance own finite launch/catch work.
"""
from ..shared import DefinitionId
from ..transport.infrastructure import InfrastructureTransportMethod
from . import base_ids as ids


def build_infrastructure_transport_methods() -> tuple[InfrastructureTransportMethod, ...]:
    return (
        InfrastructureTransportMethod(
            DefinitionId('planned.operation.mass_driver_freight'),
            'mass_driver_launch', 'kinetic_cargo_capture',
            1.0, 1.0,
            max_distance_km=12000.0, transit_speed_km_per_day=3200.0,
            payload_support_resource_id=ids.THERMAL_CONTROL_ASSEMBLIES,
            payload_support_resource_per_t=.004,
        ),
        InfrastructureTransportMethod(
            DefinitionId('planned.operation.tether_transfer'),
            'tether_momentum_exchange', 'tether_momentum_exchange',
            1.0, 1.0,
            max_distance_km=50000.0, transit_speed_km_per_day=8500.0,
            payload_support_resource_id=ids.THERMAL_CONTROL_ASSEMBLIES,
            payload_support_resource_per_t=.006,
            same_body=True,
        ),
    )
