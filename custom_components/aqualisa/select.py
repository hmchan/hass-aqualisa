"""Select platform for Aqualisa shower."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FLOW_MAX,
    FLOW_MED,
    FLOW_MIN,
    FLOW_NAME_TO_VALUE,
    FLOW_NAMES,
    KEY_LIVE_OUTLET,
    KEY_REQUEST_FLOW,
    KEY_REQUEST_OUTLET,
)
from .coordinator import SIGNAL_SHOWER_UPDATE, AqualisaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for shower_id, shower in coordinator.showers.items():
        entities.append(AqualisaFlowSelect(coordinator, shower_id, shower, entry))
        outlets = shower.get("outlets", [])
        if len(outlets) > 1:
            entities.append(AqualisaOutletSelect(coordinator, shower_id, shower, entry))

    async_add_entities(entities)


class AqualisaFlowSelect(SelectEntity):
    """Flow rate selection."""

    _attr_has_entity_name = True
    _attr_name = "Flow Rate"
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, shower_id, shower, entry):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._attr_unique_id = f"aqualisa_{shower_id}_flow_select"
        self._attr_options = list(FLOW_NAMES.values())
        self._attr_current_option = FLOW_NAMES[FLOW_MAX]
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
        if KEY_REQUEST_FLOW in data:
            try:
                val = int(data[KEY_REQUEST_FLOW])
                self._attr_current_option = FLOW_NAMES.get(val, self._attr_current_option)
            except (ValueError, TypeError):
                pass
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change flow rate."""
        flow_value = FLOW_NAME_TO_VALUE.get(option, FLOW_MAX)
        self._attr_current_option = option
        settings = self._coordinator.shower_settings.setdefault(self._shower_id, {})
        settings["flow"] = flow_value
        self.async_write_ha_state()


class AqualisaOutletSelect(SelectEntity):
    """Outlet selection (drencher/handset/bath)."""

    _attr_has_entity_name = True
    _attr_name = "Outlet"
    _attr_icon = "mdi:shower-head"

    def __init__(self, coordinator, shower_id, shower, entry):
        self._coordinator = coordinator
        self._shower_id = shower_id
        self._shower = shower
        self._outlets = shower.get("outlets", [])
        self._attr_unique_id = f"aqualisa_{shower_id}_outlet_select"
        self._attr_options = [
            o.get("name") or o.get("outletType", f"Outlet {o.get('orderNumber', '?')}")
            for o in self._outlets
        ]
        self._attr_current_option = self._attr_options[0] if self._attr_options else None
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
        if KEY_REQUEST_OUTLET in data:
            try:
                order = int(data[KEY_REQUEST_OUTLET])
                for i, o in enumerate(self._outlets):
                    if o.get("orderNumber") == order:
                        self._attr_current_option = self._attr_options[i]
                        break
            except (ValueError, TypeError, IndexError):
                pass
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change outlet."""
        self._attr_current_option = option
        # Find the outlet ID for this option
        for i, name in enumerate(self._attr_options):
            if name == option and i < len(self._outlets):
                settings = self._coordinator.shower_settings.setdefault(self._shower_id, {})
                settings["outlet_id"] = self._outlets[i].get("outletsId")
                break
        self.async_write_ha_state()
