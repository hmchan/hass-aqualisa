"""Binary sensor platform for Aqualisa shower."""

from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, KEY_LIVE_ON_OFF, KEY_SOURCE, SOURCE_POLL
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator

# A shower checks in roughly every half hour; allow a little over that before
# calling it offline.
ONLINE_TIMEOUT = 1980


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
        self._attr_is_on = self._online_from_last_seen()

    def _online_from_last_seen(self) -> bool | None:
        """Derive online state from the shower's lastSeen timestamp.

        Read through the coordinator rather than the dict captured at
        construction, since a refresh replaces the stored shower payload.

        Note that appliancesmodule/view returns lastSeen without a timezone
        (unlike push messages, which are UTC with a Z suffix). It is UK local
        time, so the naive comparison below is correct as long as Home
        Assistant runs in UK time.
        """
        shower = self._coordinator.showers.get(self._shower_id) or self._shower
        last_seen = shower.get("lastSeen")
        if not last_seen:
            return None
        try:
            dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            age = (datetime.now(dt.tzinfo) - dt).total_seconds()
        except (ValueError, TypeError):
            return None
        return age < ONLINE_TIMEOUT

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
        if data.get(KEY_SOURCE) == SOURCE_POLL:
            # A REST refresh says nothing about liveness on its own; re-derive
            # it from the lastSeen the refresh just brought in.
            self._attr_is_on = self._online_from_last_seen()
        else:
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
        if (live := self._coordinator.live_state(self._shower_id)):
            self._handle_update(live)

    @callback
    def _handle_update(self, data: dict) -> None:
        if KEY_LIVE_ON_OFF in data:
            self._attr_is_on = data[KEY_LIVE_ON_OFF] == "1"
            self.async_write_ha_state()
