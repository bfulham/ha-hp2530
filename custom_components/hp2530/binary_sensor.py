"""Port link state, and the chassis power supply and fan sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Hp2530ConfigEntry, Hp2530Coordinator
from .entity import Hp2530Entity, Hp2530PortEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Hp2530ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    switch = coordinator.data.switch
    entities: list[BinarySensorEntity] = [
        PortLink(coordinator, number) for number in switch.ports
    ]
    entities += [ChassisSensor(coordinator, index) for index in switch.sensors]
    async_add_entities(entities)


class PortLink(Hp2530PortEntity, BinarySensorEntity):
    """Link up or down. Carries what the faceplate tooltip shows."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "port_link"

    def __init__(self, coordinator: Hp2530Coordinator, number: int) -> None:
        super().__init__(coordinator, number, "link")

    @property
    def is_on(self) -> bool | None:
        return port.link if (port := self.port) else None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        if (port := self.port) is None:
            return attrs
        attrs |= {
            "speed": port.speed,
            "description": port.alias or None,
            "admin_up": port.admin_up,
        }
        if neighbor := port.neighbor:
            attrs |= {
                "neighbor": neighbor.name,
                "neighbor_port": neighbor.port_id,
                "neighbor_description": neighbor.system_descr,
            }
        return attrs


class ChassisSensor(Hp2530Entity, BinarySensorEntity):
    """A row of the HP chassis sensor table: on means a problem."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Hp2530Coordinator, index: int) -> None:
        super().__init__(coordinator, f"chassis_sensor_{index}")
        self._index = index
        # "Power Supply" -> "Power supply"; the switch names its own sensors
        self._attr_name = coordinator.data.switch.sensors[index].name.capitalize()

    @property
    def is_on(self) -> bool | None:
        sensor = self.coordinator.data.switch.sensors.get(self._index)
        if sensor is None or sensor.status in ("unknown", "not_present"):
            return None
        return sensor.status != "good"

    @property
    def extra_state_attributes(self) -> dict:
        sensor = self.coordinator.data.switch.sensors.get(self._index)
        return {"status": sensor.status if sensor else None}
