"""Sensor platform for Aqualisa shower."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FLOW_NAMES,
    KEY_LIVE_AT_TEMPERATURE,
    KEY_LIVE_FLOW,
    KEY_LIVE_ON_OFF,
    KEY_LIVE_OUTLET,
    KEY_LIVE_TEMPERATURE,
    KEY_LIVE_TIME_RUN,
    KEY_REQUEST_FLOW,
    KEY_REQUEST_TEMPERATURE,
    KEY_USAGE_AVG_TEMP,
    KEY_USAGE_RUN_TIME,
)
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.extend([
            AqualisaTemperatureSensor(coordinator, shower_id, shower, entry),
            AqualisaTargetTemperatureSensor(coordinator, shower_id, shower, entry),
            AqualisaFlowSensor(coordinator, shower_id, shower, entry),
            AqualisaRunTimeSensor(coordinator, shower_id, shower, entry),
            AqualisaTemperatureStateSensor(coordinator, shower_id, shower, entry),
        ])

    async_add_entities(entities)


class AqualisaSensorBase(SensorEntity):
    """Base class for Aqualisa sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: AqualisaCoordinator, shower_id: int, shower: dict,
        entry: ConfigEntry, key: str, name: str,
    ):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._attr_unique_id = f"aqualisa_{shower_id}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(shower_id))},
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_SHOWER_UPDATE}_{self._shower_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, data: dict) -> None:
        raise NotImplementedError


class AqualisaTemperatureSensor(AqualisaSensorBase):
    """Live water temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, shower_id, shower, entry):
        super().__init__(coordinator, shower_id, shower, entry, "live_temp", "Live Temperature")

    @callback
    def _handle_update(self, data: dict) -> None:
        if KEY_LIVE_TEMPERATURE in data:
            try:
                self._attr_native_value = float(data[KEY_LIVE_TEMPERATURE])
            except (ValueError, TypeError):
                pass
            self.async_write_ha_state()


class AqualisaTargetTemperatureSensor(AqualisaSensorBase):
    """Target/requested temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, shower_id, shower, entry):
        super().__init__(coordinator, shower_id, shower, entry, "target_temp", "Target Temperature")

    @callback
    def _handle_update(self, data: dict) -> None:
        if KEY_REQUEST_TEMPERATURE in data:
            try:
                self._attr_native_value = float(data[KEY_REQUEST_TEMPERATURE])
            except (ValueError, TypeError):
                pass
            self.async_write_ha_state()


class AqualisaFlowSensor(AqualisaSensorBase):
    """Flow rate sensor."""

    def __init__(self, coordinator, shower_id, shower, entry):
        super().__init__(coordinator, shower_id, shower, entry, "flow", "Flow Rate")

    @callback
    def _handle_update(self, data: dict) -> None:
        if KEY_LIVE_FLOW in data:
            try:
                val = int(data[KEY_LIVE_FLOW])
                self._attr_native_value = FLOW_NAMES.get(val, str(val))
            except (ValueError, TypeError):
                pass
            self.async_write_ha_state()


class AqualisaRunTimeSensor(AqualisaSensorBase):
    """Running time sensor."""

    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer"

    def __init__(self, coordinator, shower_id, shower, entry):
        super().__init__(coordinator, shower_id, shower, entry, "run_time", "Running Time")

    @callback
    def _handle_update(self, data: dict) -> None:
        if KEY_LIVE_TIME_RUN in data:
            try:
                self._attr_native_value = int(data[KEY_LIVE_TIME_RUN])
            except (ValueError, TypeError):
                pass
            self.async_write_ha_state()


class AqualisaTemperatureStateSensor(AqualisaSensorBase):
    """Temperature state (warming/cooling/at temperature)."""

    _attr_icon = "mdi:thermometer-check"

    def __init__(self, coordinator, shower_id, shower, entry):
        super().__init__(coordinator, shower_id, shower, entry, "temp_state", "Temperature State")
        self._live_temp: int | None = None
        self._request_temp: int | None = None
        self._at_temp: bool = False

    @callback
    def _handle_update(self, data: dict) -> None:
        changed = False
        if KEY_LIVE_AT_TEMPERATURE in data:
            self._at_temp = data[KEY_LIVE_AT_TEMPERATURE] == "1"
            changed = True
        if KEY_LIVE_TEMPERATURE in data:
            try:
                self._live_temp = int(data[KEY_LIVE_TEMPERATURE])
                changed = True
            except (ValueError, TypeError):
                pass
        if KEY_REQUEST_TEMPERATURE in data:
            try:
                self._request_temp = int(data[KEY_REQUEST_TEMPERATURE])
                changed = True
            except (ValueError, TypeError):
                pass

        if changed:
            if self._at_temp:
                self._attr_native_value = "At Temperature"
            elif self._live_temp is not None and self._request_temp is not None:
                if self._live_temp < self._request_temp:
                    self._attr_native_value = "Warming"
                elif self._live_temp > self._request_temp:
                    self._attr_native_value = "Cooling"
                else:
                    self._attr_native_value = "At Temperature"
            self.async_write_ha_state()
