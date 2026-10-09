"""ORM models of the shared data model (ADR-0002), grouped by area.

Importing this package registers every table on ``Base.metadata``, which Alembic's
autogenerate and the schema tests rely on.
"""

from netops.db.models._common import Observation
from netops.db.models.collection import CollectionRun
from netops.db.models.configuration import ConfigChange, ConfigVersion
from netops.db.models.credentials import CredentialProfile
from netops.db.models.diagnosis import Finding
from netops.db.models.inventory import Device, DeviceSerial, Interface, InterfaceAddress, Location
from netops.db.models.monitoring import Alarm, Event, Incident, Metric
from netops.db.models.observations import (
    ArpEntry,
    HsrpObservation,
    InterfaceSnapshot,
    MacEntry,
    NeighborObservation,
    OspfNeighborObservation,
    RouteEntry,
    StpInstanceObservation,
    StpPortObservation,
    VlanObservation,
)
from netops.db.models.topology import Link

__all__ = [
    "Alarm",
    "ArpEntry",
    "CollectionRun",
    "ConfigChange",
    "ConfigVersion",
    "CredentialProfile",
    "Device",
    "DeviceSerial",
    "Event",
    "Finding",
    "HsrpObservation",
    "Incident",
    "Interface",
    "InterfaceAddress",
    "InterfaceSnapshot",
    "Link",
    "Location",
    "MacEntry",
    "Metric",
    "NeighborObservation",
    "Observation",
    "OspfNeighborObservation",
    "RouteEntry",
    "StpInstanceObservation",
    "StpPortObservation",
    "VlanObservation",
]
