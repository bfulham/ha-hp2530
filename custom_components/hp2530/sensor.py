"""Sensors: PoE power and energy per port and in total, plus switch health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import Hp2530ConfigEntry, Hp2530Coordinator
from .data import DETECT_STATUS, Port, SwitchData
from .energy import EnergyMeter
from .entity import Hp2530Entity, Hp2530PortEntity
from .faceplate import geometry

POE_STATUS_OPTIONS = [*DETECT_STATUS.values(), "unknown"]


@dataclass(frozen=True, kw_only=True)
class SwitchSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SwitchData], float | int | None]
    exists_fn: Callable[[SwitchData], bool] = lambda _: True


SWITCH_SENSORS: tuple[SwitchSensorDescription, ...] = (
    SwitchSensorDescription(
        key="poe_power",
        translation_key="poe_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.poe_power,
        exists_fn=lambda s: s.has_poe,
    ),
    SwitchSensorDescription(
        key="poe_budget",
        translation_key="poe_budget",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.poe_budget,
        exists_fn=lambda s: s.poe_budget is not None,
    ),
    SwitchSensorDescription(
        key="poe_used_percent",
        translation_key="poe_used_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.poe_used_percent,
        exists_fn=lambda s: s.poe_budget is not None,
    ),
    SwitchSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.cpu,
        exists_fn=lambda s: s.cpu is not None,
    ),
    SwitchSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda s: s.mem_used_percent,
        exists_fn=lambda s: s.mem_total is not None,
    ),
)


@dataclass(frozen=True, kw_only=True)
class PortSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Port, tuple[float | None, float | None]], float | str | None]
    exists_fn: Callable[[Port, SwitchData], bool] = lambda _p, _s: True


PORT_SENSORS: tuple[PortSensorDescription, ...] = (
    PortSensorDescription(
        key="poe_power",
        translation_key="port_poe_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda p, _r: p.poe.power if p.poe else None,
        exists_fn=lambda p, _s: p.poe is not None and p.poe.power is not None,
    ),
    PortSensorDescription(
        key="poe_status",
        translation_key="port_poe_status",
        device_class=SensorDeviceClass.ENUM,
        options=POE_STATUS_OPTIONS,
        value_fn=lambda p, _r: p.poe.status if p.poe else None,
        exists_fn=lambda p, _s: p.poe is not None,
    ),
    PortSensorDescription(
        key="rx_rate",
        translation_key="port_rx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda _p, r: r[0],
    ),
    PortSensorDescription(
        key="tx_rate",
        translation_key="port_tx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda _p, r: r[1],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Hp2530ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    switch = coordinator.data.switch
    entities: list[SensorEntity] = [
        SwitchSensor(coordinator, description)
        for description in SWITCH_SENSORS
        if description.exists_fn(switch)
    ]
    if switch.has_port_power:
        entities.append(SwitchEnergy(coordinator))
    if switch.uptime is not None:
        entities.append(BootTime(coordinator))
    entities.append(Faceplate(coordinator))

    for number, port in switch.ports.items():
        entities += [
            PortSensor(coordinator, number, description)
            for description in PORT_SENSORS
            if description.exists_fn(port, switch)
        ]
        if port.poe is not None and port.poe.power is not None:
            entities.append(PortEnergy(coordinator, number))

    async_add_entities(entities)


class SwitchSensor(Hp2530Entity, SensorEntity):
    entity_description: SwitchSensorDescription

    def __init__(
        self, coordinator: Hp2530Coordinator, description: SwitchSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data.switch)


class PortSensor(Hp2530PortEntity, SensorEntity):
    entity_description: PortSensorDescription

    def __init__(
        self,
        coordinator: Hp2530Coordinator,
        number: int,
        description: PortSensorDescription,
    ) -> None:
        super().__init__(coordinator, number, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        if (port := self.port) is None:
            return None
        rates = self.coordinator.data.rates.get(self._number, (None, None))
        return self.entity_description.value_fn(port, rates)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        if self._metric == "poe_status" and (port := self.port) and port.poe:
            attrs |= {
                "power_class": port.poe.power_class,
                "priority": port.poe.priority,
                "enabled": port.poe.enabled,
            }
        return attrs


class _EnergyMixin:
    """kWh, integrated from the power reading at every poll.

    Survives restarts by restoring the last total. The interval across a
    restart or an outage is not counted (see energy.MAX_GAP_SECONDS).

    Listed before the coordinator entity in the bases, so that this
    _handle_coordinator_update runs rather than CoordinatorEntity's own.
    """

    coordinator: Hp2530Coordinator
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _meter: EnergyMeter

    def _watts(self) -> float | None:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()  # type: ignore[misc]
        if (last := await self.async_get_last_sensor_data()) is not None:  # type: ignore[attr-defined]
            try:
                self._meter.kwh = float(last.native_value or 0)
            except (TypeError, ValueError):
                pass
        self._meter.add(self._watts(), self.coordinator.data.timestamp)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._meter.add(self._watts(), self.coordinator.data.timestamp)
        super()._handle_coordinator_update()  # type: ignore[misc]

    @property
    def native_value(self) -> float:
        # Full resolution in the state; 30 s of a few watts is well under 1 mWh
        return round(self._meter.kwh, 9)


class PortEnergy(_EnergyMixin, Hp2530PortEntity, RestoreSensor):
    _attr_translation_key = "port_poe_energy"

    def __init__(self, coordinator: Hp2530Coordinator, number: int) -> None:
        super().__init__(coordinator, number, "poe_energy")
        self._meter = EnergyMeter()

    def _watts(self) -> float | None:
        port = self.port
        return port.poe.power if port and port.poe else None


class SwitchEnergy(_EnergyMixin, Hp2530Entity, RestoreSensor):
    _attr_translation_key = "poe_energy"

    def __init__(self, coordinator: Hp2530Coordinator) -> None:
        super().__init__(coordinator, "poe_energy")
        self._meter = EnergyMeter()

    def _watts(self) -> float | None:
        return self.coordinator.data.switch.poe_power


class BootTime(Hp2530Entity, SensorEntity):
    """When the switch last booted, from sysUpTime.

    A timestamp rather than a duration, so the state only changes on a reboot
    instead of on every poll.
    """

    _attr_translation_key = "boot_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # sysUpTime is read a few seconds after the poll starts, so the derived
    # boot time wanders by that much. Smaller moves are not a reboot.
    _JITTER = timedelta(seconds=60)

    def __init__(self, coordinator: Hp2530Coordinator) -> None:
        super().__init__(coordinator, "boot_time")
        self._boot: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        uptime = self.coordinator.data.switch.uptime
        if uptime is None:
            return self._boot
        boot = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(microsecond=0)
        if self._boot is None or abs(boot - self._boot) > self._JITTER:
            self._boot = boot
        return self._boot


class Faceplate(Hp2530Entity, SensorEntity):
    """Carries the front panel geometry for the card in its attributes."""

    _attr_translation_key = "faceplate"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset(
        {"model", "display", "width", "height", "viewbox", "generated", "ports"}
    )

    def __init__(self, coordinator: Hp2530Coordinator) -> None:
        super().__init__(coordinator, "faceplate")
        switch = coordinator.data.switch
        self._geometry = geometry(
            switch.sku,
            switch.model,
            list(switch.ports),
            {number for number, port in switch.ports.items() if port.poe},
        )

    @property
    def native_value(self) -> str:
        return self._geometry["model"] or "generic"

    @property
    def extra_state_attributes(self) -> dict:
        return self._geometry
