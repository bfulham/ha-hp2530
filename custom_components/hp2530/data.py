"""What one poll reads, and what it means.

`poll()` does the SNMP requests; `parse()` turns the answers into a SwitchData
and is a pure function, so tests drive it from a recorded dump. No Home
Assistant imports here either.

Every per-port table on the 2530 is indexed by port number, and the port
number is also the ifIndex (1-48 copper, 49-52 SFP). The PoE tables add a
group in front: `1.<port>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:  # inside Home Assistant this is a package
    from .snmp import Reader, SnmpError, Value
except ImportError:  # tools/make_fixture.py imports it as a plain module
    from snmp import Reader, SnmpError, Value  # type: ignore[no-redef]

# --- system (SNMPv2-MIB) ----------------------------------------------------
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
BRIDGE_ADDRESS = "1.3.6.1.2.1.17.1.1.0"

# --- IF-MIB -----------------------------------------------------------------
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
# ifHighSpeed, in Mb/s. ifSpeed caps at 4.29 Gb/s. Neither is 0 on a port that
# is down: the 2530 reports 10 Mb/s there, so speed is zeroed in parse().
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
# ethernetCsmacd and gigabitEthernet. VLAN interfaces are propVirtual(53) and
# the 2530's eight lo0-lo7 interfaces are softwareLoopback(24).
PORT_IF_TYPES = {6, 117}

# --- POWER-ETHERNET-MIB, RFC 3621 -------------------------------------------
PETH_ADMIN = "1.3.6.1.2.1.105.1.1.1.3"
PETH_DETECT = "1.3.6.1.2.1.105.1.1.1.6"
PETH_PRIORITY = "1.3.6.1.2.1.105.1.1.1.7"
PETH_CLASS = "1.3.6.1.2.1.105.1.1.1.10"
# pethMainPseTable, one row per PSE group: .2 power (W), .3 oper status,
# .4 consumption (whole watts), .5 usage threshold (%)
PETH_MAIN = "1.3.6.1.2.1.105.1.3.1.1"

DETECT_STATUS = {
    1: "disabled",
    2: "searching",
    3: "delivering",
    4: "fault",
    5: "test",
    6: "other_fault",
}
PRIORITY = {1: "critical", 2: "high", 3: "low"}

# --- LLDP-MIB lldpRemTable: index is <timemark>.<local port>.<remote index> --
LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_CHASSIS_SUBTYPE = "4"
LLDP_CHASSIS_ID = "5"
LLDP_PORT_ID = "7"
LLDP_PORT_DESCR = "8"
LLDP_SYS_NAME = "9"
LLDP_SYS_DESCR = "10"
LLDP_CHASSIS_LOCAL = 7

# --- HP private MIBs, read only when sysObjectID is under enterprise 11 ------
HP_ENTERPRISE = "1.3.6.1.4.1.11."
# HP-ICF-POE-MIB hpicfPoePethPsePortActualPower, milliwatts, indexed 1.<port>.
# The standard MIB has no per-port power at all.
HP_POE_POWER = "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8"
# NETSWITCH-MIB
HP_CPU = "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"
HP_MEM_TOTAL = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5.1"
HP_MEM_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1"
HP_MEM_ALLOC = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.7.1"
HP_FIRMWARE = "1.3.6.1.4.1.11.2.14.11.5.1.1.3.0"
HP_ROM = "1.3.6.1.4.1.11.2.14.11.5.1.1.4.0"
# HP-ICF-CHASSIS hpicfSensorTable: .4 status, .7 description
HP_SENSORS = "1.3.6.1.4.1.11.2.14.11.1.2.6.1"
SENSOR_STATUS = {1: "unknown", 2: "bad", 3: "warning", 4: "good", 5: "not_present"}

# --- ENTITY-MIB, for a stable identifier ------------------------------------
ENT_CLASS = "1.3.6.1.2.1.47.1.1.1.1.5"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
ENT_CLASS_CHASSIS = 3

STANDARD_WALKS = (
    IF_TYPE,
    IF_ADMIN,
    IF_OPER,
    IF_NAME,
    IF_HC_IN,
    IF_HC_OUT,
    IF_HIGH_SPEED,
    IF_ALIAS,
    PETH_ADMIN,
    PETH_DETECT,
    PETH_PRIORITY,
    PETH_CLASS,
    PETH_MAIN,
    LLDP_REM,
)
HP_WALKS = (HP_POE_POWER, HP_SENSORS)
STANDARD_SCALARS = (SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_NAME)
HP_SCALARS = (HP_CPU, HP_MEM_TOTAL, HP_MEM_FREE, HP_MEM_ALLOC, HP_FIRMWARE, HP_ROM)

# "HP J9772A 2530-48G-PoEP Switch, revision YA.15.10.0003, ROM YA.15.09 (...)"
_RE_DESCR = re.compile(r"^(?:HPE?|Aruba)\s+(?P<sku>J[A-Z]?\d{3,4}[A-Z])\s+(?P<name>\S+)")
_RE_REVISION = re.compile(r"revision\s+([A-Za-z0-9._-]+)", re.IGNORECASE)


@dataclass(slots=True)
class Neighbor:
    """What LLDP says is on the other end of a port."""

    system_name: str | None = None
    chassis_id: str | None = None
    port_id: str | None = None
    port_descr: str | None = None
    system_descr: str | None = None

    @property
    def name(self) -> str | None:
        """A name for the neighbour, if it gave one.

        The system name, else a locally assigned chassis ID: some access points
        send their hostname there and leave the system name empty.
        """
        return self.system_name or self.chassis_id


@dataclass(slots=True)
class PoePort:
    status: str
    enabled: bool | None = None
    priority: str | None = None
    # IEEE class 0-4. The MIB counts from 1 (class0(1) ... class4(5)).
    power_class: int | None = None
    # Watts, from the HP table. None where the device has no per-port meter.
    power: float | None = None


@dataclass(slots=True)
class Port:
    number: int
    name: str
    alias: str = ""
    admin_up: bool | None = None
    link: bool | None = None
    speed: int | None = None  # Mb/s, 0 when down
    in_octets: int | None = None
    out_octets: int | None = None
    poe: PoePort | None = None
    neighbor: Neighbor | None = None

    @property
    def label(self) -> str:
        """LLDP neighbour, else the port's description, else "Port N"."""
        if self.neighbor and self.neighbor.name:
            return self.neighbor.name
        return self.alias or f"Port {self.number}"


@dataclass(slots=True)
class Sensor:
    """One row of the HP chassis sensor table (power supply, fan, ...)."""

    index: int
    name: str
    status: str


@dataclass(slots=True)
class SwitchData:
    sys_name: str | None = None
    sys_descr: str | None = None
    sys_object_id: str | None = None
    uptime: int | None = None  # seconds
    sku: str | None = None  # "J9772A"
    model: str | None = None  # "2530-48G-PoEP"
    firmware: str | None = None
    rom: str | None = None
    cpu: int | None = None  # %
    mem_total: int | None = None
    mem_free: int | None = None
    mem_used: int | None = None
    poe_budget: int | None = None  # W
    poe_consumption: int | None = None  # W, whole watts only
    poe_threshold: int | None = None  # %
    sensors: dict[int, Sensor] = field(default_factory=dict)
    ports: dict[int, Port] = field(default_factory=dict)

    @property
    def is_hp(self) -> bool:
        return is_hp(self.sys_object_id)

    @property
    def has_poe(self) -> bool:
        return any(port.poe for port in self.ports.values())

    @property
    def has_port_power(self) -> bool:
        return any(port.poe and port.poe.power is not None for port in self.ports.values())

    @property
    def poe_power(self) -> float | None:
        """Total PoE draw in watts, summed from the per-port meters.

        Finer than pethMainPseConsumptionPower, which is whole watts. Falls
        back to that when the device has no per-port meter.
        """
        readings = [
            port.poe.power
            for port in self.ports.values()
            if port.poe and port.poe.power is not None
        ]
        if readings:
            return round(sum(readings), 3)
        return float(self.poe_consumption) if self.poe_consumption is not None else None

    @property
    def mem_used_percent(self) -> float | None:
        if not self.mem_total or self.mem_used is None:
            return None
        return round(self.mem_used * 100 / self.mem_total, 1)

    @property
    def poe_used_percent(self) -> float | None:
        power = self.poe_power
        if not self.poe_budget or power is None:
            return None
        return round(power * 100 / self.poe_budget, 1)


def is_hp(sys_object_id: str | None) -> bool:
    return bool(sys_object_id) and f"{sys_object_id}.".startswith(HP_ENTERPRISE)


def _text(value: Value | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    # AOS-S keeps an alias exactly as typed, leading spaces included, and pads
    # the serial number with a trailing one
    text = text.replace("\x00", "").strip()
    return text or None


def _int(value: Value | None) -> int | None:
    return value if isinstance(value, int) else None


def _mac(value: bytes) -> str:
    return ":".join(f"{b:02x}" for b in value)


def _port_of(index: str) -> int | None:
    """`1.5` -> 5 for the PoE tables. Only group 1 exists on a 2530."""
    group, _, port = index.partition(".")
    if group != "1" or not port.isdigit():
        return None
    return int(port)


def parse_descr(descr: str | None) -> tuple[str | None, str | None, str | None]:
    """(sku, model name, firmware) from sysDescr."""
    if not descr:
        return None, None, None
    sku = name = firmware = None
    if match := _RE_DESCR.match(descr):
        sku, name = match["sku"], match["name"]
    if match := _RE_REVISION.search(descr):
        firmware = match.group(1).rstrip(".,")
    return sku, name, firmware


def _neighbors(rows: dict[str, Value]) -> dict[int, Neighbor]:
    """One neighbour per local port: the lowest remote index wins."""
    by_key: dict[tuple[int, int], dict[str, Value]] = {}
    for suffix, value in rows.items():
        parts = suffix.split(".")
        if len(parts) != 4:
            continue
        column, _timemark, local, remote = parts
        if not (local.isdigit() and remote.isdigit()):
            continue
        by_key.setdefault((int(local), int(remote)), {})[column] = value

    out: dict[int, Neighbor] = {}
    for (local, _remote), cols in sorted(by_key.items()):
        if local in out:
            continue
        # Only a locally assigned chassis ID is a name. A MAC address is not.
        chassis_id = None
        if _int(cols.get(LLDP_CHASSIS_SUBTYPE)) == LLDP_CHASSIS_LOCAL:
            chassis_id = _text(cols.get(LLDP_CHASSIS_ID))
        neighbor = Neighbor(
            system_name=_text(cols.get(LLDP_SYS_NAME)),
            chassis_id=chassis_id,
            port_id=_text(cols.get(LLDP_PORT_ID)),
            port_descr=_text(cols.get(LLDP_PORT_DESCR)),
            system_descr=_text(cols.get(LLDP_SYS_DESCR)),
        )
        out[local] = neighbor
    return out


def parse(walks: dict[str, dict[str, Value]], scalars: dict[str, Value]) -> SwitchData:
    """Turn one poll's raw answers into a SwitchData. Pure."""

    def walk(base: str) -> dict[str, Value]:
        return walks.get(base) or {}

    descr = _text(scalars.get(SYS_DESCR))
    sku, model, descr_firmware = parse_descr(descr)
    uptime = _int(scalars.get(SYS_UPTIME))
    data = SwitchData(
        sys_name=_text(scalars.get(SYS_NAME)),
        sys_descr=descr,
        sys_object_id=_text(scalars.get(SYS_OBJECT_ID)),
        uptime=uptime // 100 if uptime is not None else None,
        sku=sku,
        model=model,
        firmware=_text(scalars.get(HP_FIRMWARE)) or descr_firmware,
        rom=_text(scalars.get(HP_ROM)),
        cpu=_int(scalars.get(HP_CPU)),
        mem_total=_int(scalars.get(HP_MEM_TOTAL)),
        mem_free=_int(scalars.get(HP_MEM_FREE)),
        mem_used=_int(scalars.get(HP_MEM_ALLOC)),
    )

    main = walk(PETH_MAIN)
    data.poe_budget = _int(main.get("2.1"))
    data.poe_consumption = _int(main.get("4.1"))
    data.poe_threshold = _int(main.get("5.1"))

    sensor_rows = walk(HP_SENSORS)
    for suffix, value in sensor_rows.items():
        column, _, row = suffix.partition(".")
        if column != "4" or not row.isdigit():
            continue
        name = _text(sensor_rows.get(f"7.{row}")) or f"Sensor {row}"
        name = re.sub(r"\s+Sensor$", "", name, flags=re.IGNORECASE)
        data.sensors[int(row)] = Sensor(
            index=int(row),
            name=name,
            status=SENSOR_STATUS.get(_int(value) or 0, "unknown"),
        )

    names = walk(IF_NAME)
    admin = walk(IF_ADMIN)
    oper = walk(IF_OPER)
    speed = walk(IF_HIGH_SPEED)
    alias = walk(IF_ALIAS)
    hc_in = walk(IF_HC_IN)
    hc_out = walk(IF_HC_OUT)
    for index, if_type in walk(IF_TYPE).items():
        if not index.isdigit() or _int(if_type) not in PORT_IF_TYPES:
            continue
        number = int(index)
        link = _int(oper.get(index)) == 1 if index in oper else None
        data.ports[number] = Port(
            number=number,
            name=_text(names.get(index)) or index,
            alias=_text(alias.get(index)) or "",
            admin_up=_int(admin.get(index)) == 1 if index in admin else None,
            link=link,
            speed=_int(speed.get(index)) if link else 0,
            in_octets=_int(hc_in.get(index)),
            out_octets=_int(hc_out.get(index)),
        )
    data.ports = dict(sorted(data.ports.items()))

    poe_admin = walk(PETH_ADMIN)
    poe_detect = walk(PETH_DETECT)
    poe_priority = walk(PETH_PRIORITY)
    poe_class = walk(PETH_CLASS)
    poe_power = walk(HP_POE_POWER)
    for index, detect in poe_detect.items():
        number = _port_of(index)
        if number is None or number not in data.ports:
            continue
        raw_class = _int(poe_class.get(index))
        milliwatts = _int(poe_power.get(index))
        data.ports[number].poe = PoePort(
            status=DETECT_STATUS.get(_int(detect) or 0, "unknown"),
            enabled=_int(poe_admin.get(index)) == 1 if index in poe_admin else None,
            priority=PRIORITY.get(_int(poe_priority.get(index)) or 0),
            power_class=raw_class - 1 if raw_class and 1 <= raw_class <= 5 else None,
            power=milliwatts / 1000 if milliwatts is not None else None,
        )

    for number, neighbor in _neighbors(walk(LLDP_REM)).items():
        if number in data.ports:
            data.ports[number].neighbor = neighbor

    return data


async def poll(reader: Reader) -> SwitchData:
    """One full read. Raises SnmpError if the agent does not answer."""
    scalars = await reader.get(list(STANDARD_SCALARS))
    hp = is_hp(_text(scalars.get(SYS_OBJECT_ID)))
    if hp:
        scalars |= await reader.get(list(HP_SCALARS))
    walks: dict[str, dict[str, Value]] = {}
    for base in STANDARD_WALKS + (HP_WALKS if hp else ()):
        walks[base] = await reader.walk(base)
    return parse(walks, scalars)


@dataclass(slots=True)
class Identity:
    name: str | None
    descr: str | None
    sys_object_id: str | None
    serial: str | None
    mac: str | None

    @property
    def unique_id(self) -> str | None:
        """Chassis serial, else the bridge MAC. Never the address."""
        return self.serial or self.mac


async def identify(reader: Reader) -> Identity:
    """For the config flow: who is this, and does it answer at all."""
    scalars = await reader.get([SYS_NAME, SYS_DESCR, SYS_OBJECT_ID, BRIDGE_ADDRESS])
    if SYS_OBJECT_ID not in scalars and SYS_DESCR not in scalars:
        raise SnmpError("the agent answered without a system group")
    classes = await reader.walk(ENT_CLASS)
    serials = await reader.walk(ENT_SERIAL)
    serial = None
    # The row the device itself calls a chassis: index 1 on a 2530, 1001 on a
    # 2540. Other rows hold modules, fans and placeholders.
    for index in sorted(
        (i for i, cls in classes.items() if _int(cls) == ENT_CLASS_CHASSIS),
        key=lambda i: [int(p) for p in i.split(".") if p.isdigit()],
    ):
        if candidate := _text(serials.get(index)):
            serial = candidate
            break
    mac_raw = scalars.get(BRIDGE_ADDRESS)
    mac = _mac(mac_raw) if isinstance(mac_raw, bytes) and len(mac_raw) == 6 else None
    return Identity(
        name=_text(scalars.get(SYS_NAME)),
        descr=_text(scalars.get(SYS_DESCR)),
        sys_object_id=_text(scalars.get(SYS_OBJECT_ID)),
        serial=serial,
        mac=mac,
    )
