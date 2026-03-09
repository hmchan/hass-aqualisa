"""Binary sensor platform for Aqualisa shower."""

from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, KEY_LIVE_ON_OFF
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.append(AqualisaOnlineSensor(coordinator, shower_id, shower, entry))
        entities.append(AqualisaRunningSensor(coordinator, shower_id, shower, entry))

    async_add_entities(entities)


class AqualisaOnlineSensor(BinarySensorEntity):
    """Shower online/connectivity status."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, shower_id, shower, entry):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._attr_unique_id = f"aqualisa_{shower_id}_online"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(shower_id))},
        }
        # Determine initial state from lastSeen
        last_seen = shower.get("lastSeen")
        if last_seen:
            try:
                dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                age = (datetime.now(dt.tzinfo) - dt).total_seconds()
                self._attr_is_on = age < 1980
            except (ValueError, TypeError):
                self._attr_is_on = None
        else:
            self._attr_is_on = None

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
        # Any push message means the device is online
        self._attr_is_on = True
        self.async_write_ha_state()


class AqualisaRunningSensor(BinarySensorEntity):
    """Shower running status."""

    _attr_has_entity_name = True
    _attr_name = "Running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, shower_id, shower, entry):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._attr_unique_id = f"aqualisa_{shower_id}_running"
        self._attr_is_on = False
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
        if KEY_LIVE_ON_OFF in data:
            self._attr_is_on = data[KEY_LIVE_ON_OFF] == "1"
            self.async_write_ha_state()
