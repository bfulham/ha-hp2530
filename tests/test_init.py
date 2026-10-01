"""Setup, entities and energy accumulation, against the recorded switch."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from .conftest import HP_POE_POWER_PORT5, IF_HC_IN_PORT5, Replay


class Clock:
    """Stands in for time.monotonic() in the coordinator."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock():
    clock = Clock()
    with patch("custom_components.hp2530.coordinator.time", clock):
        yield clock


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_not_ready_when_silent(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    mock_switch.fail = True
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_entities(
    hass: HomeAssistant,
    mock_switch: Replay,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await _setup(hass, config_entry)

    power = hass.states.get("sensor.test_switch_port_5_poe_power")
    assert float(power.state) == pytest.approx(6.875)
    assert power.attributes["port"] == "5"
    assert power.attributes["metric"] == "poe_power"
    assert power.attributes["label"] == "Alias 5"

    status = hass.states.get("sensor.test_switch_port_16_poe_status")
    assert status.state == "other_fault"
    assert hass.states.get("sensor.test_switch_port_38_poe_status").attributes[
        "power_class"
    ] == 4

    link = hass.states.get("binary_sensor.test_switch_port_47_link")
    assert link.state == "on"
    assert link.attributes["speed"] == 1000
    assert link.attributes["label"] == "neighbor-2"
    assert link.attributes["neighbor_port"] == "gigabitEthernet 1/0/8"
    assert hass.states.get("binary_sensor.test_switch_port_2_link").state == "off"

    assert float(hass.states.get("sensor.test_switch_poe_power").state) == pytest.approx(40.707)
    assert hass.states.get("sensor.test_switch_poe_budget").state == "764"
    assert hass.states.get("sensor.test_switch_cpu").state == "37"
    assert hass.states.get("sensor.test_switch_memory_used").state == "39.1"
    assert hass.states.get("binary_sensor.test_switch_power_supply").state == "off"
    assert hass.states.get("binary_sensor.test_switch_fan").state == "off"

    faceplate = hass.states.get("sensor.test_switch_faceplate")
    assert faceplate.state == "J9772A"
    assert len(faceplate.attributes["ports"]) == 52

    # The SFP ports have links but no PoE entities
    assert hass.states.get("binary_sensor.test_switch_port_49_link") is not None
    assert hass.states.get("sensor.test_switch_port_49_poe_power") is None
    # Rates are there, but off by default
    rate = entity_registry.async_get("sensor.test_switch_port_5_receive_rate")
    assert rate is not None and rate.disabled

    entry = entity_registry.async_get("sensor.test_switch_port_5_poe_power")
    info = dr.async_get(hass).async_get(entry.device_id)
    assert (info.manufacturer, info.model, info.model_id) == ("HP", "2530-48G-PoEP", "J9772A")
    assert info.sw_version == "YA.15.10.0003"
    assert info.serial_number == "SG00000000"


async def test_energy_accumulates(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry, clock: Clock
) -> None:
    await _setup(hass, config_entry)
    for entity_id in ("sensor.test_switch_port_5_poe_energy", "sensor.test_switch_poe_energy"):
        state = hass.states.get(entity_id)
        assert float(state.state) == 0
        # What the Energy dashboard needs to accept the sensor
        assert state.attributes["device_class"] == "energy"
        assert state.attributes["state_class"] == "total_increasing"
        assert state.attributes["unit_of_measurement"] == "kWh"

    # 30 s later port 5 draws 7.125 W: the average of 6.875 and 7.125 is 7 W
    clock.now += 30
    mock_switch.values[HP_POE_POWER_PORT5] = 7125
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    energy = float(hass.states.get("sensor.test_switch_port_5_poe_energy").state)
    assert energy == pytest.approx(7.0 * 30 / 3_600_000, rel=1e-3)
    total = float(hass.states.get("sensor.test_switch_poe_energy").state)
    assert total == pytest.approx((40.707 + 40.957) / 2 * 30 / 3_600_000, rel=1e-3)


async def test_energy_restored(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry, clock: Clock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.test_switch_port_5_poe_energy", "1.5"),
                {"native_value": 1.5, "native_unit_of_measurement": "kWh"},
            )
        ],
    )
    await _setup(hass, config_entry)
    assert float(hass.states.get("sensor.test_switch_port_5_poe_energy").state) == 1.5

    clock.now += 3600
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    # An hour is longer than the gap allowed, so nothing is added across it
    assert float(hass.states.get("sensor.test_switch_port_5_poe_energy").state) == 1.5

    clock.now += 360
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.test_switch_port_5_poe_energy").state) == (
        pytest.approx(1.5 + 6.875 * 360 / 3_600_000, rel=1e-6)
    )


async def test_rates(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry, clock: Clock
) -> None:
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert coordinator.data.rates == {}

    clock.now += 30
    mock_switch.values[IF_HC_IN_PORT5] += 3_750_000  # 30 Mbit in 30 s
    await coordinator.async_refresh()
    assert coordinator.data.rates[5] == (1.0, 0.0)

    # A counter that goes backwards was reset: no rate rather than a negative one
    clock.now += 30
    mock_switch.values[IF_HC_IN_PORT5] = 0
    await coordinator.async_refresh()
    assert coordinator.data.rates[5][0] is None
