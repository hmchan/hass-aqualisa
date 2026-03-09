"""Aqualisa Cloud API client."""

import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp

from .const import BASE_URL_EU, BASE_URL_UK, REGION_EU

MAX_RETRIES = 10
RETRY_BACKOFF_BASE = 1  # seconds

_LOGGER = logging.getLogger(__name__)


class AqualisaApiError(Exception):
    """Aqualisa API error."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class AqualisaApi:
    """Aqualisa Cloud API client."""

    def __init__(self, session: aiohttp.ClientSession, region: str = "uk"):
        self._session = session
        self._region = region
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._access_token_expires_at: float = 0
        self._refresh_token_expires_at: float = 0

    @property
    def base_url(self) -> str:
        if self._region == REGION_EU:
            return BASE_URL_EU
        return BASE_URL_UK

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    @property
    def token_data(self) -> dict:
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "access_token_expires_at": self._access_token_expires_at,
            "refresh_token_expires_at": self._refresh_token_expires_at,
        }

    def restore_tokens(self, data: dict) -> None:
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        self._access_token_expires_at = data.get("access_token_expires_at", 0)
        self._refresh_token_expires_at = data.get("refresh_token_expires_at", 0)

    async def _request(
        self, method: str, path: str, role: str = "appuserrole",
        body: dict | None = None, auth: bool = True,
    ) -> dict:
        url = f"{self.base_url}/{role}/{path}" if role else f"{self.base_url}/{path}"
        headers = {"accept": "application/json"}
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                if method == "GET":
                    async with self._session.get(url, headers=headers) as resp:
                        data = await resp.json()
                else:
                    headers["Content-Type"] = "application/json"
                    async with self._session.post(url, headers=headers, json=body or {}) as resp:
                        data = await resp.json()

                if data.get("status") != "1":
                    errors = data.get("errors", [])
                    codes = [e.get("messageCode", "") for e in errors]
                    raise AqualisaApiError(f"API error: {codes}", errors)

                return data

            except (OSError, aiohttp.ClientError) as err:
                last_err = err
                delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                _LOGGER.warning(
                    "Aqualisa API request failed (attempt %d/%d): %s. Retrying in %ds",
                    attempt + 1, MAX_RETRIES, err, delay,
                )
                await asyncio.sleep(delay)

        raise last_err

    def _store_tokens(self, details: dict) -> None:
        now = time.time()
        self._access_token = details["accessToken"]
        self._access_token_expires_at = now + details.get("expiresIn", 3600)
        self._refresh_token = details.get("refreshToken", self._refresh_token)
        if details.get("refreshTokenExpiresIn"):
            self._refresh_token_expires_at = now + details["refreshTokenExpiresIn"]

    async def login(self, username: str, password: str) -> dict:
        """Login and return response details (may contain mfaDetails)."""
        data = await self._request("POST", "authmodule/login", role="publicrole", body={
            "accountType": "AppUser",
            "username": username,
            "password": password,
            "rememberMe": True,
        }, auth=False)
        details = data.get("details", {})
        if details.get("accessToken"):
            self._store_tokens(details)
        return details

    async def mfa_challenge(self, mfa_token: str, challenge_type: str) -> dict:
        """Request MFA challenge (SMS or Email)."""
        data = await self._request("POST", "authmodule/mfa/challenge", role="publicrole", body={
            "mfaToken": mfa_token,
            "challengeType": challenge_type,
        }, auth=False)
        return data.get("details", {})

    async def mfa_login(self, mfa_token: str, mfa_code: str, challenge_type: str) -> dict:
        """Complete MFA login."""
        data = await self._request("POST", "authmodule/mfa/login", role="publicrole", body={
            "mfaToken": mfa_token,
            "mfaCode": mfa_code,
            "challengeType": challenge_type,
            "rememberMe": True,
        }, auth=False)
        details = data.get("details", {})
        self._store_tokens(details)
        return details

    async def ensure_token(self) -> None:
        """Refresh access token if expired."""
        if time.time() < self._access_token_expires_at - 60:
            return
        if time.time() >= self._refresh_token_expires_at - 60:
            raise AqualisaApiError("Session expired, re-login required")
        _LOGGER.debug("Refreshing Aqualisa access token")
        data = await self._request("POST", "authmodule/refresh", role="publicrole", body={
            "accessToken": self._access_token,
            "refreshToken": self._refresh_token,
        }, auth=False)
        self._store_tokens(data.get("details", {}))

    async def list_homes(self) -> list[dict]:
        await self.ensure_token()
        data = await self._request("GET", "homesmodule/list")
        return data.get("details", {}).get("homes", [])

    async def list_showers(self, home_id: int) -> list[dict]:
        await self.ensure_token()
        data = await self._request("GET", f"appliancesmodule/list?id={home_id}")
        return data.get("details", {}).get("appliances", [])

    async def view_shower(self, shower_id: int) -> dict:
        await self.ensure_token()
        data = await self._request("GET", f"appliancesmodule/view?Id={shower_id}")
        return data.get("details", {})

    async def start_shower(
        self, shower_id: int, outlet_id: int, flow: int, temperature: float,
        duration: int,
    ) -> dict:
        await self.ensure_token()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        data = await self._request("POST", "appliancecontrolmodule/start", body={
            "appliancesId": shower_id,
            "outletsId": outlet_id,
            "flow": flow,
            "temperature": temperature,
            "timestamp": timestamp,
            "maximumDuration": duration,
        })
        return data.get("details", {})

    async def stop_shower(self, shower_id: int) -> dict:
        await self.ensure_token()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        data = await self._request("POST", "appliancecontrolmodule/stop", body={
            "appliancesId": shower_id,
            "timestamp": timestamp,
        })
        return data.get("details", {})

    async def update_shower(
        self, shower_id: int, outlet_id: int, flow: int, temperature: float,
    ) -> dict:
        await self.ensure_token()
        data = await self._request("POST", "appliancecontrolmodule/edit", body={
            "appliancesId": shower_id,
            "outletsId": outlet_id,
            "flow": flow,
            "temperature": temperature,
        })
        return data.get("details", {})

    async def register_push(self, installation_id: str, fcm_token: str) -> dict:
        """Register for push notifications."""
        await self.ensure_token()
        url = self.base_url.replace("v1", "notificationsmodule").rstrip("/") + "/apppushsubscriptions/register"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        _LOGGER.debug("Push registration URL: %s", url)
        async with self._session.post(url, headers=headers, json={
            "installationId": installation_id,
            "pnsHandle": fcm_token,
            "platform": 4,
        }) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.warning("Push registration HTTP %d: %s", resp.status, text[:200])
                return {}
            data = await resp.json(content_type=None)
        if data.get("status") != "1":
            _LOGGER.warning("Push notification registration failed: %s", data.get("errors"))
        else:
            _LOGGER.info("Push notification registration successful")
        return data

    async def get_all_showers(self) -> list[dict]:
        """Get all showers across all homes with full details."""
        homes = await self.list_homes()
        showers = []
        for home in homes:
            home_id = home["homesId"]
            home_name = home.get("name", "Home")
            appliances = await self.list_showers(home_id)
            for app in appliances:
                details = await self.view_shower(app["applianceId"])
                details["_home_id"] = home_id
                details["_home_name"] = home_name
                showers.append(details)
        return showers
