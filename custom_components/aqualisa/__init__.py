"""Aqualisa Smart Shower integration."""

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AqualisaApi
from .const import CONF_REGION, DOMAIN
from .coordinator import AqualisaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.WATER_HEATER, Platform.SENSOR, Platform.SELECT, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aqualisa from a config entry."""
    from .api import AqualisaApiError

    session = async_get_clientsession(hass)
    api = AqualisaApi(session, entry.data.get(CONF_REGION, "uk"))

    def _persist_tokens(token_data: dict) -> None:
        new_data = dict(entry.data)
        new_data["token_data"] = token_data
        hass.config_entries.async_update_entry(entry, data=new_data)

    api.set_token_update_callback(_persist_tokens)

    # Restore tokens, fall back to re-login if refresh token is invalid/expired
    token_data = entry.data.get("token_data", {})
    logged_in = False
    if token_data and token_data.get("access_token"):
        api.restore_tokens(token_data)
        try:
            await api.ensure_token()
            logged_in = True
        except AqualisaApiError:
            _LOGGER.warning("Stored tokens invalid, attempting re-login")

    if not logged_in:
        try:
            # Clear stale tokens before re-login attempt
            api.clear_tokens()
            details = await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
            if not api.access_token:
                # Login returned MFA challenge — can't auto-re-login
                _LOGGER.error("Aqualisa login requires MFA, please reconfigure the integration")
                raise ConfigEntryAuthFailed("Login requires MFA verification")
        except AqualisaApiError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

    # Store credentials for re-login on token expiry
    api.set_relogin_credentials(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    coordinator = AqualisaCoordinator(hass, api)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Aqualisa config entry."""
    coordinator: AqualisaCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
