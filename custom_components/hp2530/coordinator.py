"""One poll per interval, for the whole switch."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .data import SwitchData, poll
from .snmp import Reader, SnmpError

_LOGGER = logging.getLogger(__name__)

type Hp2530ConfigEntry = ConfigEntry[Hp2530Coordinator]


@dataclass(slots=True)
class Snapshot:
    switch: SwitchData
    # time.monotonic() when the poll finished. Energy is integrated against
    # this, so every port in one poll shares one timestamp.
    timestamp: float
    # Port number -> (rx, tx) in Mbit/s, from the previous poll's counters
    rates: dict[int, tuple[float | None, float | None]] = field(default_factory=dict)


def _rate(now: int | None, before: int | None, seconds: float) -> float | None:
    if now is None or before is None or seconds <= 0 or now < before:
        # A counter that went backwards was reset or wrapped
        return None
    return round((now - before) * 8 / seconds / 1_000_000, 3)


class Hp2530Coordinator(DataUpdateCoordinator[Snapshot]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        reader: Reader,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.reader = reader

    async def _async_update_data(self) -> Snapshot:
        try:
            switch = await poll(self.reader)
        except SnmpError as err:
            raise UpdateFailed(f"SNMP: {err}") from err
        if not switch.ports:
            raise UpdateFailed("the switch reported no ports")
        timestamp = time.monotonic()

        rates: dict[int, tuple[float | None, float | None]] = {}
        if (previous := self.data) is not None:
            seconds = timestamp - previous.timestamp
            for number, port in switch.ports.items():
                if (before := previous.switch.ports.get(number)) is None:
                    continue
                rates[number] = (
                    _rate(port.in_octets, before.in_octets, seconds),
                    _rate(port.out_octets, before.out_octets, seconds),
                )
        return Snapshot(switch=switch, timestamp=timestamp, rates=rates)
