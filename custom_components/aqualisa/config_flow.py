"""Config flow for Aqualisa integration."""

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import AqualisaApi, AqualisaApiError
from .const import CONF_MFA_TOKEN, CONF_MFA_TYPE, CONF_REGION, DOMAIN, REGION_EU, REGION_UK

_LOGGER = logging.getLogger(__name__)


class AqualisaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aqualisa."""

    VERSION = 1

    def __init__(self):
        self._username: str = ""
        self._password: str = ""
        self._region: str = REGION_UK
        self._mfa_token: str = ""
        self._mfa_type: str = ""
        self._mfa_types: list[str] = []
        self._token_data: dict = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial login step."""
        errors = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._region = user_input.get(CONF_REGION, REGION_UK)

            try:
                session = aiohttp.ClientSession()
                try:
                    api = AqualisaApi(session, self._region)
                    details = await api.login(self._username, self._password)
                    self._token_data = api.token_data

                    # Check for MFA
                    mfa_details = details.get("mfaDetails", {})
                    if mfa_details and mfa_details.get("bEnabled"):
                        self._mfa_token = mfa_details.get("mfaToken", "")
                        self._mfa_types = mfa_details.get("enabledMfaChallengeTypes", [])
                        self._token_data = {}  # Not authenticated yet

                        if len(self._mfa_types) == 1:
                            self._mfa_type = self._mfa_types[0]
                            # Auto-request challenge
                            await api.mfa_challenge(self._mfa_token, self._mfa_type)
                            return await self.async_step_mfa_code()

                        return await self.async_step_mfa_select()

                    # No MFA, login complete
                    return self._create_entry()

                finally:
                    await session.close()

            except AqualisaApiError as err:
                error_codes = [e.get("messageCode", "") for e in err.errors]
                if "username_or_password_incorrect" in error_codes:
                    errors["base"] = "invalid_auth"
                elif "account_locked" in error_codes:
                    errors["base"] = "account_locked"
                else:
                    errors["base"] = "cannot_connect"
                    _LOGGER.error("Login failed: %s", err)
            except Exception:
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_REGION, default=REGION_UK): vol.In({
                    REGION_UK: "United Kingdom",
                    REGION_EU: "Europe",
                }),
            }),
            errors=errors,
        )

    async def async_step_mfa_select(self, user_input=None):
        """Select MFA challenge type."""
        errors = {}

        if user_input is not None:
            self._mfa_type = user_input[CONF_MFA_TYPE]
            try:
                session = aiohttp.ClientSession()
                try:
                    api = AqualisaApi(session, self._region)
                    await api.mfa_challenge(self._mfa_token, self._mfa_type)
                    return await self.async_step_mfa_code()
                finally:
                    await session.close()
            except AqualisaApiError:
                errors["base"] = "mfa_failed"

        options = {t: t for t in self._mfa_types}
        return self.async_show_form(
            step_id="mfa_select",
            data_schema=vol.Schema({
                vol.Required(CONF_MFA_TYPE): vol.In(options),
            }),
            errors=errors,
        )

    async def async_step_mfa_code(self, user_input=None):
        """Enter MFA code."""
        errors = {}

        if user_input is not None:
            mfa_code = user_input["mfa_code"]
            try:
                session = aiohttp.ClientSession()
                try:
                    api = AqualisaApi(session, self._region)
                    await api.mfa_login(self._mfa_token, mfa_code, self._mfa_type)
                    self._token_data = api.token_data
                    return self._create_entry()
                finally:
                    await session.close()
            except AqualisaApiError as err:
                error_codes = [e.get("messageCode", "") for e in err.errors]
                if "mfa_code_invalid" in error_codes:
                    errors["base"] = "invalid_mfa"
                else:
                    errors["base"] = "mfa_failed"

        return self.async_show_form(
            step_id="mfa_code",
            data_schema=vol.Schema({
                vol.Required("mfa_code"): str,
            }),
            errors=errors,
            description_placeholders={"mfa_type": self._mfa_type},
        )

    def _create_entry(self):
        """Create the config entry."""
        return self.async_create_entry(
            title=self._username,
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_REGION: self._region,
                "token_data": self._token_data,
            },
        )
