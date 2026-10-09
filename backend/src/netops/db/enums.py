"""Closed value sets of the shared data model, stored as native PostgreSQL enum types.

The PostgreSQL type name is the snake_case class name (``DeviceType`` -> ``device_type``).
Values are persisted, so treat them as stable identifiers: adding a value needs a migration
(``ALTER TYPE ... ADD VALUE``); renaming or removing one needs a data migration.
"""

import re
from enum import StrEnum

# --- Inventory (M1/M2) --------------------------------------------------------------------


class DeviceType(StrEnum):
    SWITCH = "switch"
    L3_SWITCH = "l3_switch"
    ROUTER = "router"
    FIREWALL = "firewall"
    AP = "ap"
    WLC = "wlc"
    UNKNOWN = "unknown"


class DeviceRole(StrEnum):
    CORE = "core"
    DISTRIBUTION = "distribution"
    ACCESS = "access"
    EDGE = "edge"
    UNKNOWN = "unknown"


class OsFamily(StrEnum):
    IOS = "ios"
    IOSXE = "iosxe"
    PFSENSE = "pfsense"
    OTHER = "other"
    UNKNOWN = "unknown"


class Reachability(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class DiscoverySource(StrEnum):
    """How a device first entered the inventory."""

    SEED = "seed"
    CDP = "cdp"
    LLDP = "lldp"
    ARP = "arp"
    MANUAL = "manual"


class InterfaceKind(StrEnum):
    PHYSICAL = "physical"
    PORT_CHANNEL = "port_channel"
    SVI = "svi"
    LOOPBACK = "loopback"
    TUNNEL = "tunnel"
    MANAGEMENT = "management"
    OTHER = "other"


class Duplex(StrEnum):
    FULL = "full"
    HALF = "half"
    AUTO = "auto"
    UNKNOWN = "unknown"


class SwitchportMode(StrEnum):
    """Operational mode; "dynamic auto/desirable" ports are stored as what they negotiated."""

    ACCESS = "access"
    TRUNK = "trunk"
    ROUTED = "routed"
    UNKNOWN = "unknown"


class VlanStatus(StrEnum):
    """IOS ``show vlan`` status: act/lshut and sus/lshut are SHUTDOWN, act/unsup UNSUPPORTED."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    SHUTDOWN = "shutdown"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


# --- Topology (M1) ------------------------------------------------------------------------


class LinkSource(StrEnum):
    CDP = "cdp"
    LLDP = "lldp"
    INFERRED = "inferred"
    MANUAL = "manual"


class NeighborProtocol(StrEnum):
    CDP = "cdp"
    LLDP = "lldp"


# --- Collection runs ----------------------------------------------------------------------


class CollectionKind(StrEnum):
    """What a collection run collected; each observation table belongs to exactly one kind."""

    FACTS = "facts"
    INTERFACES = "interfaces"
    NEIGHBORS = "neighbors"
    VLANS = "vlans"
    MAC_TABLE = "mac_table"
    ARP_TABLE = "arp_table"
    ROUTES = "routes"
    STP = "stp"
    HSRP = "hsrp"
    OSPF = "ospf"
    CONFIG = "config"


class CollectionTrigger(StrEnum):
    SCHEDULED = "scheduled"
    DISCOVERY = "discovery"
    EVENT = "event"
    MANUAL = "manual"
    PRE_CHANGE = "pre_change"
    POST_CHANGE = "post_change"


class CollectionStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


# --- Observations -------------------------------------------------------------------------


class MacEntryType(StrEnum):
    DYNAMIC = "dynamic"
    STATIC = "static"
    OTHER = "other"


class RouteProtocol(StrEnum):
    CONNECTED = "connected"
    LOCAL = "local"
    STATIC = "static"
    OSPF = "ospf"
    OTHER = "other"


class StpPortRole(StrEnum):
    ROOT = "root"
    DESIGNATED = "designated"
    ALTERNATE = "alternate"
    BACKUP = "backup"
    DISABLED = "disabled"


class StpPortState(StrEnum):
    FORWARDING = "forwarding"
    BLOCKING = "blocking"
    LEARNING = "learning"
    LISTENING = "listening"
    DISABLED = "disabled"
    # IOS "BKN*": blocked by an inconsistency (root guard, PVID/type mismatch, loop guard).
    BROKEN = "broken"


class HsrpState(StrEnum):
    ACTIVE = "active"
    STANDBY = "standby"
    LISTEN = "listen"
    SPEAK = "speak"
    LEARN = "learn"
    INIT = "init"


class OspfNeighborState(StrEnum):
    """RFC 2328 neighbor states; the DR/BDR suffix IOS prints (``FULL/DR``) is not part of it."""

    DOWN = "down"
    ATTEMPT = "attempt"
    INIT = "init"
    TWO_WAY = "2way"
    EXSTART = "exstart"
    EXCHANGE = "exchange"
    LOADING = "loading"
    FULL = "full"


# --- Monitoring, alarms and diagnosis (M3/M6) ---------------------------------------------


class EventKind(StrEnum):
    SYSLOG = "syslog"
    TRAP = "trap"


class Severity(StrEnum):
    """Alarm and finding severity, most severe first."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"
    INFO = "info"


class AlarmState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"


class IncidentState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


# --- Configuration (M4/M5) ----------------------------------------------------------------


class ConfigTrigger(StrEnum):
    SCHEDULED = "scheduled"
    CHANGE_EVENT = "change_event"
    PRE_CHANGE = "pre_change"
    POST_CHANGE = "post_change"
    MANUAL = "manual"


class ChangeOrigin(StrEnum):
    PLATFORM = "platform"
    EXTERNAL = "external"


ALL_ENUMS: tuple[type[StrEnum], ...] = (
    DeviceType,
    DeviceRole,
    OsFamily,
    Reachability,
    DiscoverySource,
    InterfaceKind,
    Duplex,
    SwitchportMode,
    VlanStatus,
    LinkSource,
    NeighborProtocol,
    CollectionKind,
    CollectionTrigger,
    CollectionStatus,
    MacEntryType,
    RouteProtocol,
    StpPortRole,
    StpPortState,
    HsrpState,
    OspfNeighborState,
    EventKind,
    Severity,
    AlarmState,
    IncidentState,
    ConfigTrigger,
    ChangeOrigin,
)


def pg_type_name(enum_cls: type[StrEnum]) -> str:
    """PostgreSQL type name for an enum class: ``OspfNeighborState`` -> ``ospf_neighbor_state``."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", enum_cls.__name__).lower()
