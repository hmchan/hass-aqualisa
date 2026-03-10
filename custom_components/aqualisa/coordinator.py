"""Data coordinator for Aqualisa integration."""

import asyncio
import logging
import uuid
from datetime import datetime

from firebase_messaging import FcmPushClient, FcmRegisterConfig, FcmPushClientConfig

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .api import AqualisaApi
from .const import (
    DOMAIN,
    FCM_API_KEY,
    FCM_APP_ID,
    FCM_PROJECT_ID,
    FCM_SENDER_ID,
    KEY_APPLIANCES_ID,
    KEY_TIMESTAMP,
)

_LOGGER = logging.getLogger(__name__)

SIGNAL_SHOWER_UPDATE = f"{DOMAIN}_shower_update"

FCM_WATCHDOG_INTERVAL = 60  # seconds between watchdog checks
FCM_STARTUP_RETRIES = 10
FCM_CREDENTIALS_STORAGE_KEY = f"{DOMAIN}_fcm_credentials"
FCM_CREDENTIALS_STORAGE_VERSION = 1


class AqualisaCoordinator:
    """Coordinates data for all Aqualisa showers."""

    def __init__(self, hass: HomeAssistant, api: AqualisaApi):
        self.hass = hass
        self.api = api
        self.showers: dict[int, dict] = {}  # shower_id -> shower data
        # Shared settings per shower (written by select/number, read by water_heater)
        self.shower_settings: dict[int, dict] = {}  # shower_id -> {flow, outlet_id, duration}
        self._fcm_client: FcmPushClient | None = None
        self._fcm_credentials: dict | None = None
        self._installation_id: str = str(uuid.uuid4())
        self._watchdog_task: asyncio.Task | None = None
        self._shutting_down: bool = False
        self._credential_store = Store(hass, FCM_CREDENTIALS_STORAGE_VERSION, FCM_CREDENTIALS_STORAGE_KEY)

    async def async_setup(self) -> None:
        """Initial data fetch and FCM setup."""
        await self.async_refresh()
        # Restore persisted FCM credentials
        stored = await self._credential_store.async_load()
        if stored:
            self._fcm_credentials = stored.get("credentials")
            self._installation_id = stored.get("installation_id", self._installation_id)
            _LOGGER.debug("Restored persisted FCM credentials")
        await self._async_start_fcm()
        # Start watchdog to auto-restart FCM if it dies
        self._watchdog_task = asyncio.create_task(self._async_fcm_watchdog())

    async def async_refresh(self) -> None:
        """Fetch all shower data from the API."""
        showers = await self.api.get_all_showers()
        for shower in showers:
            shower_id = shower.get("appliancesId") or shower.get("id")
            if shower_id:
                self.showers[shower_id] = shower
        _LOGGER.debug("Refreshed %d showers", len(self.showers))

    def _on_notification(self, notification: dict, persistent_id: str, obj=None) -> None:
        """Handle incoming FCM notification."""
        _LOGGER.debug("FCM raw notification: %s", notification)

        # Try to extract the data payload
        raw_data = notification.get("data") or notification
        parsed = self._parse_push_message(raw_data)
        if not parsed:
            _LOGGER.debug("Could not parse FCM message: %s", notification)
            return

        shower_id_str = parsed.get(KEY_APPLIANCES_ID)
        if not shower_id_str:
            _LOGGER.debug("No appliancesId in FCM message: %s", parsed)
            return

        # Check timestamp freshness (discard if >15s old)
        ts = parsed.get(KEY_TIMESTAMP)
        if ts:
            try:
                msg_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age = (datetime.now(tz=msg_time.tzinfo) - msg_time).total_seconds()
                if age > 15:
                    _LOGGER.debug("Discarding stale push message (%.1fs old)", age)
                    return
            except (ValueError, TypeError):
                pass

        shower_id = int(shower_id_str)
        _LOGGER.info("FCM update for shower %d: %s", shower_id, parsed)

        # Update shower live data
        if shower_id in self.showers:
            if "_live" not in self.showers[shower_id]:
                self.showers[shower_id]["_live"] = {}
            self.showers[shower_id]["_live"].update(parsed)

        # Notify entities
        async_dispatcher_send(self.hass, f"{SIGNAL_SHOWER_UPDATE}_{shower_id}", parsed)

    def _on_credentials_updated(self, credentials: dict) -> None:
        """Handle FCM credentials update."""
        _LOGGER.debug("FCM credentials updated")
        self._fcm_credentials = credentials
        # Persist credentials so we reuse the same push token after restart
        self.hass.async_create_task(
            self._credential_store.async_save({
                "credentials": credentials,
                "installation_id": self._installation_id,
            })
        )

    async def _async_start_fcm(self) -> None:
        """Start FCM push notification listener with retries."""
        fcm_config = FcmRegisterConfig(
            project_id=FCM_PROJECT_ID,
            app_id=FCM_APP_ID,
            api_key=FCM_API_KEY,
            messaging_sender_id=FCM_SENDER_ID,
        )

        client_config = FcmPushClientConfig(
            connection_retry_count=10,
            log_warn_limit=5,
        )

        http_session = async_get_clientsession(self.hass)

        for attempt in range(FCM_STARTUP_RETRIES):
            if self._shutting_down:
                return
            try:
                self._fcm_client = FcmPushClient(
                    callback=self._on_notification,
                    fcm_config=fcm_config,
                    credentials=self._fcm_credentials,
                    credentials_updated_callback=self._on_credentials_updated,
                    config=client_config,
                    http_client_session=http_session,
                )

                _LOGGER.info("Starting Aqualisa FCM push client (attempt %d)...", attempt + 1)
                fcm_token = await self._fcm_client.checkin_or_register()
                _LOGGER.info("FCM checkin/register complete, token: %s...", fcm_token[:20])

                # Register push token with Aqualisa
                if fcm_token:
                    try:
                        await self.api.register_push(self._installation_id, fcm_token)
                    except Exception:
                        _LOGGER.exception("Failed to register push token with Aqualisa")
                else:
                    _LOGGER.error("Could not obtain push token - live updates will not work")

                await self._fcm_client.start()
                _LOGGER.info("Aqualisa FCM listener started")
                return  # Success

            except Exception:
                delay = min(2 ** attempt, 60)
                _LOGGER.warning(
                    "FCM startup failed (attempt %d/%d), retrying in %ds",
                    attempt + 1, FCM_STARTUP_RETRIES, delay, exc_info=True,
                )
                await asyncio.sleep(delay)

        _LOGGER.error("Failed to start FCM listener after %d attempts", FCM_STARTUP_RETRIES)

    async def _async_fcm_watchdog(self) -> None:
        """Monitor FCM client and restart it if it dies."""
        while not self._shutting_down:
            await asyncio.sleep(FCM_WATCHDOG_INTERVAL)
            if self._shutting_down:
                break
            if self._fcm_client and not self._fcm_client.is_started():
                _LOGGER.warning("FCM client is not running, restarting...")
                try:
                    await self._fcm_client.stop()
                except Exception:
                    pass
                self._fcm_client = None
                await self._async_start_fcm()

    def _parse_push_message(self, raw) -> dict | None:
        """Parse FCM message into dict. Handles both dict and pipe-delimited string formats."""
        if isinstance(raw, dict):
            # If the dict already has the keys we need, return it directly
            if any(k in raw for k in (KEY_APPLIANCES_ID, "live_on_off")):
                return {k: str(v) for k, v in raw.items()}
            # Check for nested message/body
            msg = raw.get("message", "") or raw.get("body", "")
            if isinstance(msg, dict):
                return msg
            if isinstance(msg, str) and msg:
                raw = msg
            else:
                # Try all string values for pipe-delimited format
                for v in raw.values():
                    if isinstance(v, str) and "|" in v:
                        raw = v
                        break
                else:
                    return None

        if not isinstance(raw, str) or not raw:
            return None

        result = {}
        parts = raw.split("|")
        for part in parts:
            # Format: <key>:<value> or key:value (may have angle brackets)
            cleaned = part.replace(">:<", "|").replace("<", "").replace(">", "")
            segments = cleaned.split("|") if "|" in cleaned else cleaned.split(":", 1)
            if len(segments) == 2 and segments[0] and segments[1]:
                result[segments[0].strip()] = segments[1].strip()

        return result if result else None

    async def async_shutdown(self) -> None:
        """Shut down FCM listener and watchdog."""
        self._shutting_down = True
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        if self._fcm_client and self._fcm_client.is_started():
            await self._fcm_client.stop()
            _LOGGER.info("Aqualisa FCM listener stopped")
