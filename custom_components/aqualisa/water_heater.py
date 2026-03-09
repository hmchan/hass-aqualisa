"""Water heater platform for Aqualisa shower."""

import logging
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DURATION_DEFAULT,
    FLOW_MAX,
    FLOW_NAMES,
    KEY_LIVE_ON_OFF,
    KEY_LIVE_TEMPERATURE,
    KEY_REQUEST_ON_OFF,
    KEY_REQUEST_TEMPERATURE,
    TEMP_DEFAULT,
    TEMP_MAX,
    TEMP_MIN,
)
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator

_LOGGER = logging.getLogger(__name__)

STATE_OFF = "off"
STATE_ON = "on"
OPERATION_LIST = [STATE_OFF, STATE_ON]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water heater entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.append(AqualisaWaterHeater(coordinator, shower_id, shower, entry))

    async_add_entities(entities)


class AqualisaWaterHeater(WaterHeaterEntity):
    """Aqualisa shower as a water heater entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_operation_list = OPERATION_LIST

    def __init__(
        self, coordinator: AqualisaCoordinator, shower_id: int, shower: dict,
        entry: ConfigEntry,
    ):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._entry = entry
        self._is_on = False
        self._target_temp = float(TEMP_DEFAULT)
        self._current_temp: float | None = None
        self._selected_flow = FLOW_MAX
        self._duration = DURATION_DEFAULT

        location = shower.get("location", "Shower")
        serial = shower.get("serialNumber", "unknown")
        self._attr_unique_id = f"aqualisa_{shower_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(shower_id))},
            "name": f"Aqualisa {location}",
            "manufacturer": "Aqualisa",
            "model": shower.get("controllerPartNumber", "Smart Shower"),
            "sw_version": shower.get("firmwareVersion"),
            "serial_number": serial,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to push updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_SHOWER_UPDATE}_{self._shower_id}",
                self._handle_push_update,
            )
        )

    @callback
    def _handle_push_update(self, data: dict) -> None:
        """Handle FCM push data."""
        if KEY_LIVE_ON_OFF in data:
            self._is_on = data[KEY_LIVE_ON_OFF] == "1"
        if KEY_REQUEST_ON_OFF in data:
            req = data[KEY_REQUEST_ON_OFF] == "1"
            if not self._is_on:
                self._is_on = req
        if KEY_LIVE_TEMPERATURE in data:
            try:
                self._current_temp = float(data[KEY_LIVE_TEMPERATURE])
            except (ValueError, TypeError):
                pass
        if KEY_REQUEST_TEMPERATURE in data:
            try:
                self._target_temp = float(data[KEY_REQUEST_TEMPERATURE])
            except (ValueError, TypeError):
                pass
        self.async_write_ha_state()

    @property
    def current_operation(self) -> str:
        return STATE_ON if self._is_on else STATE_OFF

    @property
    def target_temperature(self) -> float:
        return self._target_temp

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            self._target_temp = temp
            if self._is_on:
                outlet_id = self._get_outlet_id()
                if outlet_id is not None:
                    await self._coordinator.api.update_shower(
                        self._shower_id, outlet_id, self._selected_flow, self._target_temp,
                    )
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode (on/off)."""
        if operation_mode == STATE_ON:
            await self.async_turn_on()
        else:
            await self.async_turn_off()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the shower."""
        outlet_id = self._get_outlet_id()
        if outlet_id is None:
            _LOGGER.error("No outlet available for shower %d", self._shower_id)
            return
        settings = self._coordinator.shower_settings.get(self._shower_id, {})
        flow = settings.get("flow", self._selected_flow)
        duration = settings.get("duration", self._duration)
        await self._coordinator.api.start_shower(
            self._shower_id, outlet_id, flow,
            self._target_temp, duration,
        )
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the shower."""
        await self._coordinator.api.stop_shower(self._shower_id)
        self._is_on = False
        self.async_write_ha_state()

    def _get_outlet_id(self) -> int | None:
        """Get the current outlet ID from shared settings or default to first."""
        settings = self._coordinator.shower_settings.get(self._shower_id, {})
        if "outlet_id" in settings:
            return settings["outlet_id"]
        outlets = self._shower.get("outlets", [])
        if not outlets:
            return None
        return outlets[0].get("outletsId")
