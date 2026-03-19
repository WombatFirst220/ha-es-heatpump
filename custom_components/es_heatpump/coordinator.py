"""Data coordinator for ES Heatpump integration."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DATA_PATH,
    DATA_PAYLOAD,
    LOGIN_PATH,
    DOMAIN,
    SESSION_COOKIE_NAME,
)

_LOGGER = logging.getLogger(__name__)

# Force re-login after this many seconds (portal session timeout is ~60 min)
SESSION_TTL = 3300  # 55 minutes – slightly under portal timeout


def _b64(value: str) -> str:
    """Base64-encode a string, as required by the myheatpump.com login API."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


class ESHeatpumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Coordinator that manages authentication and data fetching from myheatpump.com.

    Verified API (reverse-engineered via Chrome DevTools, March 2026):
      Login  : POST /a/login
               Form fields: username (Base64), password (Base64),
                            validCode (empty), loginValidCode (empty), __url (empty)
               Session  : JSESSIONID + heatpump.session.id cookies (auto-managed by aiohttp)
               Success  : JSON body contains "success": true  (or code 0 / code 200)

      Data   : POST /a/amt/desktop/load
               Form fields: ctrlPermi=1
               Response : application/json  – nested dict with parXX keys
    """

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        base_url: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._session_age: float = 0.0

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _session_expired(self) -> bool:
        return (time.monotonic() - self._session_age) > SESSION_TTL

    def _has_session_cookie(self, session: aiohttp.ClientSession) -> bool:
        """Return True if the aiohttp jar already holds a valid session cookie."""
        jar = session.cookie_jar
        for cookie in jar:
            if cookie.key == SESSION_COOKIE_NAME:
                return True
        return False

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """
        Authenticate against myheatpump.com.

        The portal requires username and password to be Base64-encoded.
        Three additional form fields (validCode, loginValidCode, __url) must be
        present but can be empty.  The server sets JSESSIONID + heatpump.session.id
        cookies which aiohttp's shared CookieJar carries automatically on every
        subsequent request to the same domain.
        """
        session = async_get_clientsession(self.hass)
        login_url = f"{self._base_url}{LOGIN_PATH}"

        payload = {
            "username":       _b64(self._username),
            "password":       _b64(self._password),
            "validCode":      "",   # CAPTCHA – not used for API access
            "loginValidCode": "",
            "__url":          "",
        }

        _LOGGER.debug("ES Heatpump: authenticating as %s", self._username)

        try:
            async with asyncio.timeout(20):
                resp = await session.post(
                    login_url,
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    allow_redirects=False,   # login returns JSON, not a redirect
                )
                resp.raise_for_status()
                result: dict = await resp.json(content_type=None)

        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise ConfigEntryAuthFailed(
                    f"Login rejected (HTTP {err.status}) for {self._username}"
                ) from err
            raise UpdateFailed(f"Login HTTP error {err.status}: {err.message}") from err
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Login request failed: {err}") from err

        # ── Parse JSON success indicator ───────────────────────────────
        # Confirmed live response: {"msg": "Login successful!"}
        # Also handle: {"success": true}, {"code": 0}, {"code": 200}
        msg_text = str(result.get("msg") or result.get("message") or "").lower()
        success = (
            result.get("success") is True
            or result.get("code") in (0, 200, "0", "200")
            or "success" in msg_text
        )
        if not success:
            msg = result.get("msg") or result.get("message") or str(result)
            _LOGGER.error("ES Heatpump: login failed – portal response: %s", msg)
            raise ConfigEntryAuthFailed(
                f"Login rejected by portal for {self._username}: {msg}"
            )

        self._session_age = time.monotonic()
        _LOGGER.debug(
            "ES Heatpump: login successful, session cookies set by server"
        )

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    async def _fetch_data(self) -> dict[str, Any]:
        """
        POST /a/amt/desktop/load with ctrlPermi=1.
        Returns the raw JSON dict from the portal.
        Session cookies are sent automatically by aiohttp's CookieJar.
        """
        session = async_get_clientsession(self.hass)
        data_url = f"{self._base_url}{DATA_PATH}"

        try:
            async with asyncio.timeout(20):
                resp = await session.post(
                    data_url,
                    data=DATA_PAYLOAD,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                resp.raise_for_status()
                raw: dict = await resp.json(content_type=None)

        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                # Session invalidated on server side → force re-login
                self._session_age = 0.0
                raise UpdateFailed(
                    "Session expired (HTTP %d) – will re-login on next poll" % err.status
                ) from err
            raise UpdateFailed(f"Data fetch HTTP error {err.status}: {err.message}") from err
        except Exception as err:
            raise UpdateFailed(f"Data fetch failed: {err}") from err

        # If the server returns a not-logged-in indicator inside the JSON
        code = raw.get("code")
        if code in (401, 403, "401", "403"):
            self._session_age = 0.0
            raise UpdateFailed("Portal reports session invalid – will re-login")

        return raw

    # ------------------------------------------------------------------
    # Response normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
        """
        Flatten the portal JSON into {par_id: float_value}.

        The /a/amt/desktop/load endpoint returns a nested structure like:
          {
            "code": 0,
            "data": {
              "par1": "5.2",
              "par2": "35.1",
              ...
              "deviceList": [...],     ← ignored
              "alarmList": [...],      ← ignored
            }
          }

        We extract every key that looks like "parN" or "parNN" from any level.
        Unknown keys are silently skipped so future portal changes don't break HA.
        """
        import re

        par_pattern = re.compile(r"^par\d+$")
        result: dict[str, float | None] = {}

        def _extract(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if par_pattern.match(str(k)):
                        result[k] = _safe_float(v)
                    elif isinstance(v, (dict, list)):
                        _extract(v)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item)

        _extract(raw)

        if not result:
            raise UpdateFailed(
                "No parXX keys found in portal response. "
                f"Top-level keys: {list(raw.keys())[:8]}. "
                "Please open a GitHub issue with your portal's response structure."
            )

        _LOGGER.debug("ES Heatpump: received %d parameters from portal", len(result))
        return result

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Main polling loop: re-login when needed, then fetch sensor data."""
        if self._session_age == 0.0 or self._session_expired():
            await self._login()

        raw = await self._fetch_data()
        return self._normalize(raw)

    async def async_validate_credentials(self) -> bool:
        """
        Validate credentials during config flow setup.
        Raises ConfigEntryAuthFailed on bad credentials.
        Raises UpdateFailed on network/portal errors.
        """
        await self._login()
        await self._fetch_data()   # confirm data access works too
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    """Convert a raw portal value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None
