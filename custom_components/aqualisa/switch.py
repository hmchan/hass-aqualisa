"""Switch platform for Aqualisa shower."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DURATION_DEFAULT,
    FLOW_MAX,
    KEY_LIVE_ON_OFF,
    KEY_REQUEST_ON_OFF,
    TEMP_DEFAULT,
)
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.append(AqualisaShowerSwitch(coordinator, shower_id, shower, entry))

    async_add_entities(entities)


class AqualisaShowerSwitch(SwitchEntity):
    """Simple on/off switch for the Aqualisa shower."""

    _attr_has_entity_name = True
    _attr_name = "Shower"
    _attr_icon = "mdi:shower-head"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self, coordinator: AqualisaCoordinator, shower_id: int, shower: dict,
        entry: ConfigEntry,
    ):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._attr_unique_id = f"aqualisa_{shower_id}_switch"
        self._attr_is_on = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(shower_id))},
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
            self._attr_is_on = data[KEY_LIVE_ON_OFF] == "1"
        elif KEY_REQUEST_ON_OFF in data:
            self._attr_is_on = data[KEY_REQUEST_ON_OFF] == "1"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the shower."""
        outlet_id = self._get_outlet_id()
        if outlet_id is None:
            _LOGGER.error("No outlet available for shower %d", self._shower_id)
            return
        settings = self._coordinator.shower_settings.get(self._shower_id, {})
        flow = settings.get("flow", FLOW_MAX)
        duration = settings.get("duration", DURATION_DEFAULT)
        temp = settings.get("temperature", TEMP_DEFAULT)
        await self._coordinator.api.start_shower(
            self._shower_id, outlet_id, flow, temp, duration,
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the shower."""
        await self._coordinator.api.stop_shower(self._shower_id)
        self._attr_is_on = False
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
