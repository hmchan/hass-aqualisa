"""Number platform for Aqualisa shower."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DURATION_DEFAULT
from .coordinator import AqualisaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.append(AqualisaDurationNumber(coordinator, shower_id, shower, entry))

    async_add_entities(entities)


class AqualisaDurationNumber(NumberEntity):
    """Max shower duration setting."""

    _attr_has_entity_name = True
    _attr_name = "Max Duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 60
    _attr_native_max_value = 3600
    _attr_native_step = 60
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, shower_id, shower, entry):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._attr_unique_id = f"aqualisa_{shower_id}_duration"
        self._attr_native_value = DURATION_DEFAULT
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(shower_id))},
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set duration."""
        self._attr_native_value = int(value)
        settings = self._coordinator.shower_settings.setdefault(self._shower_id, {})
        settings["duration"] = int(value)
        self.async_write_ha_state()
