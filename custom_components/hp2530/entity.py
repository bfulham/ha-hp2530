"""Entity base classes."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Hp2530Coordinator
from .data import Port


class Hp2530Entity(CoordinatorEntity[Hp2530Coordinator]):
    """Anything that belongs to the switch. One device per switch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Hp2530Coordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        switch = coordinator.data.switch
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        mac = entry.data.get("mac")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            name=entry.title,
            manufacturer="HP" if switch.is_hp else None,
            model=switch.model or (switch.sys_descr or "")[:64] or None,
            model_id=switch.sku,
            sw_version=switch.firmware,
            hw_version=switch.rom,
            serial_number=entry.data.get("serial"),
            # The 2530 web UI is plain http out of the box
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )


class Hp2530PortEntity(Hp2530Entity):
    """An entity for one port.

    The `port` and `metric` attributes are how the faceplate card finds its
    entities, so renaming an entity or its ID breaks nothing. Names stay
    "Port N ..." so entity IDs do not move when a neighbour or a description
    changes; what is plugged in is in the `label` attribute.
    """

    _unrecorded_attributes = frozenset({"port", "metric"})

    def __init__(self, coordinator: Hp2530Coordinator, number: int, metric: str) -> None:
        self._number = number
        self._metric = metric
        super().__init__(coordinator, f"port{number}_{metric}")
        self._attr_translation_placeholders = {"port": str(number)}

    @property
    def port(self) -> Port | None:
        return self.coordinator.data.switch.ports.get(self._number)

    @property
    def available(self) -> bool:
        return super().available and self.port is not None

    @property
    def extra_state_attributes(self) -> dict:
        port = self.port
        return {
            "port": str(self._number),
            "metric": self._metric,
            "label": port.label if port else None,
        }
