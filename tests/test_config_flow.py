"""Config, reconfigure and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hp2530.const import DOMAIN

from .conftest import Replay

V2C = {"host": " 192.0.2.10 ", "port": 161, "snmp_version": "2c", "community": "public"}
V3 = {
    "username": "ha",
    "auth_protocol": "sha",
    "auth_key": "authpass1",
    "priv_protocol": "aes",
    "priv_key": "privpass1",
}


async def test_v2c(hass: HomeAssistant, mock_switch: Replay) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], V2C)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Switch"
    assert result["data"]["host"] == "192.0.2.10"
    assert result["data"]["serial"] == "SG00000000"
    assert result["result"].unique_id == "SG00000000"


async def test_cannot_connect_then_recover(hass: HomeAssistant, mock_switch: Replay) -> None:
    mock_switch.fail = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], V2C)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_switch.fail = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], V2C)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_v3(hass: HomeAssistant, mock_switch: Replay) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**V2C, "snmp_version": "3"}
    )
    assert result["step_id"] == "v3"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**V3, "priv_key": "short"}
    )
    assert result["errors"] == {"priv_key": "key_too_short"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], V3)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["username"] == "ha"
    assert "community" not in result["data"]


async def test_already_configured(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**V2C, "host": "192.0.2.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Same switch at a new address: the entry follows it
    assert config_entry.data["host"] == "192.0.2.99"


async def test_reconfigure(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**V2C, "community": "other"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["community"] == "other"


async def test_reconfigure_to_another_switch(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    mock_switch.values["1.3.6.1.2.1.47.1.1.1.1.11.1"] = b"SG99999999"
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], V2C)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"


async def test_options(
    hass: HomeAssistant, mock_switch: Replay, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 60}
