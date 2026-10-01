"""HP 2530 switch: PoE power and energy, ports and health over SNMP."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.singleton import singleton
from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
from pysnmp.hlapi.v3arch.asyncio.cmdgen import LCD

from .const import (
    CARD_FILENAME,
    CARD_URL,
    DATA_CARD,
    DATA_ENGINE,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import Hp2530ConfigEntry, Hp2530Coordinator
from .snmp import SnmpClient, create_engine

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


@singleton(DATA_ENGINE)
async def async_get_engine(hass: HomeAssistant) -> SnmpEngine:
    """One SNMP engine for every switch, built off the event loop."""
    engine = await hass.async_add_executor_job(create_engine)

    @callback
    def _shutdown(_event: Event) -> None:
        LCD.unconfigure(engine, None)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)
    return engine


def _card_mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


async def _register_card(hass: HomeAssistant) -> None:
    """Serve the faceplate card from the integration and load it on every
    dashboard, so there is no Lovelace resource to add by hand."""
    if hass.data.get(DATA_CARD):
        return
    path = Path(__file__).parent / "www" / CARD_FILENAME
    mtime = await hass.async_add_executor_job(_card_mtime, path)
    if mtime is None:
        _LOGGER.warning("%s is missing; the faceplate card is unavailable", path)
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    # The mtime busts the browser cache when an update ships a new card
    add_extra_js_url(hass, f"{CARD_URL}?v={mtime}")
    hass.data[DATA_CARD] = True


async def async_setup_entry(hass: HomeAssistant, entry: Hp2530ConfigEntry) -> bool:
    from .config_flow import credentials

    engine = await async_get_engine(hass)
    client = SnmpClient(credentials(dict(entry.data)), engine)
    coordinator = Hp2530Coordinator(
        hass,
        entry,
        client,
        int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    # Entities are built from what the first poll finds, so it has to succeed
    # before the platforms load. Failing here raises ConfigEntryNotReady.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await _register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Hp2530ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: Hp2530ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
