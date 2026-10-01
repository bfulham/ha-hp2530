"""The parser, against a recorded J9772A (2530-48G-PoE+)."""

from __future__ import annotations

import pytest

from custom_components.hp2530.data import (
    HP_POE_POWER,
    HP_SENSORS,
    SYS_OBJECT_ID,
    identify,
    parse_descr,
    poll,
)

from .conftest import Replay


async def test_system(replay: Replay) -> None:
    switch = await poll(replay)
    assert switch.sys_name == "Test Switch"
    assert switch.is_hp
    assert (switch.sku, switch.model) == ("J9772A", "2530-48G-PoEP")
    assert (switch.firmware, switch.rom) == ("YA.15.10.0003", "YA.15.09")
    assert switch.uptime == 8_407_685  # 97 days, 7:28:05
    assert switch.cpu == 37
    # NETSWITCH-MIB: column 6 is free, column 7 allocated
    assert switch.mem_used_percent == pytest.approx(39.1)


async def test_chassis_sensors(replay: Replay) -> None:
    switch = await poll(replay)
    assert {s.name: s.status for s in switch.sensors.values()} == {
        "Power Supply": "good",
        "Fan": "good",
    }


async def test_ports_exclude_vlans_and_loopbacks(replay: Replay) -> None:
    switch = await poll(replay)
    # ifIndex 102-161 are VLAN interfaces and 12516-12523 are lo0-lo7
    assert list(switch.ports) == list(range(1, 53))


async def test_poe_status(replay: Replay) -> None:
    switch = await poll(replay)
    by_status: dict[str, list[int]] = {}
    for number, port in switch.ports.items():
        if port.poe:
            by_status.setdefault(port.poe.status, []).append(number)
    assert by_status["delivering"] == [5, 9, 10, 11, 12, 14, 15, 18, 38]
    assert by_status["other_fault"] == [16, 17, 24]
    assert by_status["disabled"] == [47, 48]
    # The SFP ports have no PoE at all
    assert all(switch.ports[n].poe is None for n in (49, 50, 51, 52))


async def test_poe_power(replay: Replay) -> None:
    switch = await poll(replay)
    assert switch.ports[5].poe.power == pytest.approx(6.875)
    assert switch.ports[38].poe.power == pytest.approx(7.876)
    assert switch.ports[16].poe.power == 0
    # The sum of the per-port meters, finer than the switch's whole-watt total
    assert switch.poe_power == pytest.approx(40.707)
    assert switch.poe_consumption == 41
    assert switch.poe_budget == 764
    assert switch.poe_used_percent == pytest.approx(5.3)


async def test_poe_class_and_priority(replay: Replay) -> None:
    switch = await poll(replay)
    assert (switch.ports[5].poe.power_class, switch.ports[5].poe.priority) == (3, "low")
    assert (switch.ports[38].poe.power_class, switch.ports[38].poe.priority) == (4, "critical")
    assert switch.ports[47].poe.enabled is False
    assert switch.ports[5].poe.enabled is True


async def test_links(replay: Replay) -> None:
    switch = await poll(replay)
    assert switch.ports[4].link and switch.ports[4].speed == 1000
    assert switch.ports[43].link and switch.ports[43].speed == 10
    assert switch.ports[2].link is False and switch.ports[2].speed == 0


async def test_labels(replay: Replay) -> None:
    switch = await poll(replay)
    # LLDP system name wins over the port description
    assert switch.ports[47].label == "neighbor-2"
    assert switch.ports[47].alias == "Alias 47"
    assert switch.ports[47].neighbor.port_id == "gigabitEthernet 1/0/8"
    # No system name, but a locally assigned chassis ID: the AP's hostname
    assert switch.ports[38].label == "neighbor-1.example.net"
    assert switch.ports[1].label == "Alias 1"
    assert switch.ports[7].label == "Port 7"


async def test_non_hp_device_reads_no_private_mibs(replay: Replay) -> None:
    replay.values[SYS_OBJECT_ID] = "1.3.6.1.4.1.9.1.1"
    switch = await poll(replay)
    assert not switch.is_hp
    assert HP_POE_POWER not in replay.walked
    assert HP_SENSORS not in replay.walked
    assert switch.cpu is None and switch.sensors == {}
    # PoE status still comes from the standard MIB, but there is no meter per
    # port, so the total falls back to the whole-watt figure
    assert switch.has_poe and not switch.has_port_power
    assert switch.poe_power == 41.0


async def test_identify(replay: Replay) -> None:
    identity = await identify(replay)
    assert identity.name == "Test Switch"
    # The chassis row of ENTITY-MIB; the switch pads it with a space
    assert identity.serial == "SG00000000"
    assert identity.unique_id == "SG00000000"


@pytest.mark.parametrize(
    ("descr", "expected"),
    [
        (
            "HP J9772A 2530-48G-PoEP Switch, revision YA.15.10.0003, ROM YA.15.09 (/ws/x)",
            ("J9772A", "2530-48G-PoEP", "YA.15.10.0003"),
        ),
        (
            "Aruba JL357A 2540-48G-PoE+-4SFP+ Switch, revision YC.16.11.0029, ROM YC.16.01",
            ("JL357A", "2540-48G-PoE+-4SFP+", "YC.16.11.0029"),
        ),
        ("Linux router 6.1", (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_parse_descr(descr: str | None, expected: tuple) -> None:
    assert parse_descr(descr) == expected
