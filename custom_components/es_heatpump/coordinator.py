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
    DEVICE_LIST_PATH,
    LOGIN_PATH,
    REALDATA_PATH,
    SETDATA_READ_PATH,
    SETDATA_WRITE_PATH,
    SETDATA_FORM_PATH,
    DOMAIN,
    SESSION_COOKIE_NAME,
)
from .metadata import Stammdaten, aus_formularkopf, aus_geraeteliste
from .settings import SETTINGS

_LOGGER = logging.getLogger(__name__)

# Force re-login after this many seconds (portal session timeout ~60 min)
SESSION_TTL = 3300  # 55 minutes – slightly under portal timeout


def _b64(value: str) -> str:
    """Base64-encode a string, as required by the myheatpump.com login API."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


class ESHeatpumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Coordinator that manages authentication and data fetching from myheatpump.com.

    Verified API flow (reverse-engineered via Chrome DevTools, March 2026):

      Step 1 – Login
        POST /a/login
        Payload : username=<Base64>, password=<Base64>,
                  validCode=, loginValidCode=, __url=
        Response: {"msg": "Login successful!"} (and sets JSESSIONID cookie)

      Step 2 – Device discovery (once after login)
        POST /a/amt/deviceList/listData
        Payload : (empty)
        Response: JSON list of devices, each with "mn" and "devid" fields

      Step 3 – Sensor data (every poll interval)
        POST /a/amt/realdata/get
        Payload : mn=<device mn>, devid=<device devid>
        Response: flat JSON  {"par1": 2.0, "par2": 0.0, ..., "mn": ..., "devid": ...}
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
        # Device identifiers discovered after login
        self._mn: str | None = None
        self._devid: str | None = None
        # Diagnostic flag — log non-par response keys once per session
        self._logged_non_par_keys: bool = False
        # Stammdaten der Anlage (Modell, Seriennummern, Garantie, Installateur).
        # Fallen bei der Geraetesuche mit ab und aendern sich praktisch nie.
        self.stammdaten: Stammdaten = Stammdaten()
        self._kopf_gelesen: bool = False

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _session_expired(self) -> bool:
        return (time.monotonic() - self._session_age) > SESSION_TTL

    # ------------------------------------------------------------------
    # Step 1 – Login
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """
        Authenticate against myheatpump.com.
        Credentials must be Base64-encoded in the POST body.
        On success the server sets JSESSIONID + heatpump.session.id cookies,
        which aiohttp's shared CookieJar carries on all subsequent requests.
        """
        session = async_get_clientsession(self.hass)
        login_url = f"{self._base_url}{LOGIN_PATH}"

        payload = {
            "username":       _b64(self._username),
            "password":       _b64(self._password),
            "validCode":      "",   # CAPTCHA – not required for API access
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
                    allow_redirects=False,
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

        # ── Detect success ─────────────────────────────────────────────
        # Confirmed live response: {"msg": "Login successful!"}
        # Also handle: {"success": true}, {"code": 0}, {"code": 200}
        msg_text = str(result.get("msg") or result.get("message") or "").lower()
        success = (
            result.get("success") is True
            or result.get("code") in (0, 200, "0", "200")
            or "success" in msg_text
        )
        if not success:
            raw_msg = result.get("msg") or result.get("message") or str(result)
            _LOGGER.error("ES Heatpump: login failed – portal says: %s", raw_msg)
            raise ConfigEntryAuthFailed(
                f"Login rejected by portal for {self._username}: {raw_msg}"
            )

        self._session_age = time.monotonic()
        # Reset device IDs so they are re-fetched after every fresh login
        self._mn = None
        self._devid = None
        _LOGGER.debug("ES Heatpump: login successful")

    # ------------------------------------------------------------------
    # Step 2 – Device discovery
    # ------------------------------------------------------------------

    async def _discover_device(self) -> None:
        """
        Fetch the device list and store mn + devid of the first heat pump found.
        Called once after each login.
        """
        session = async_get_clientsession(self.hass)
        list_url = f"{self._base_url}{DEVICE_LIST_PATH}"

        try:
            async with asyncio.timeout(20):
                resp = await session.post(
                    list_url,
                    data={},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                resp.raise_for_status()
                result: dict = await resp.json(content_type=None)

        except Exception as err:
            raise UpdateFailed(f"Device list fetch failed: {err}") from err

        # ── Extract mn + devid from the first device ───────────────────
        # Known response shapes:
        #   {"rows": [{"mn": "99999", "devid": "1", ...}, ...]}
        #   {"data": {"rows": [...]}}
        #   [{"mn": "99999", "devid": "1", ...}]
        devices: list[dict] = []

        if isinstance(result, list):
            devices = result
        elif isinstance(result, dict):
            for key in ("rows", "data", "list", "records", "result"):
                candidate = result.get(key)
                if isinstance(candidate, list) and candidate:
                    devices = candidate
                    break
                if isinstance(candidate, dict):
                    for sub_key in ("rows", "list", "records"):
                        sub = candidate.get(sub_key)
                        if isinstance(sub, list) and sub:
                            devices = sub
                            break
                    if devices:
                        break

        if not devices:
            raise UpdateFailed(
                f"No devices found in portal response. "
                f"Top-level keys: {list(result.keys()) if isinstance(result, dict) else type(result)}. "
                "Please open a GitHub issue."
            )

        first = devices[0]
        self._mn    = str(first.get("mn")    or first.get("Mn")    or "")
        self._devid = str(first.get("devid") or first.get("DevId") or first.get("id") or "1")

        # Stammdaten fallen hier kostenlos mit ab: Modell, beide Seriennummern,
        # Garantiedatum, Inbetriebnahme und Installateur stehen bereits in
        # dieser Antwort. Ein Fehler darf die Geraetesuche nie anhalten.
        try:
            self.stammdaten = aus_geraeteliste(first)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ES Heatpump: Stammdaten nicht lesbar: %s", err)

        if not self._mn:
            raise UpdateFailed(
                f"Could not find 'mn' field in device entry: {list(first.keys())}. "
                "Please open a GitHub issue."
            )

        _LOGGER.info(
            "ES Heatpump: discovered device  mn=%s  devid=%s",
            self._mn, self._devid,
        )

    # ------------------------------------------------------------------
    # Step 3 – Sensor data
    # ------------------------------------------------------------------

    async def _fetch_realdata(self) -> dict[str, Any]:
        """
        POST /a/amt/realdata/get  with  mn=XXXX&devid=X.
        Returns the raw JSON dict from the portal.
        """
        session = async_get_clientsession(self.hass)
        data_url = f"{self._base_url}{REALDATA_PATH}"

        payload = {"mn": self._mn, "devid": self._devid}

        try:
            async with asyncio.timeout(20):
                resp = await session.post(
                    data_url,
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                resp.raise_for_status()
                raw: dict = await resp.json(content_type=None)

        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                self._session_age = 0.0
                raise UpdateFailed(
                    f"Session expired (HTTP {err.status}) – will re-login on next poll"
                ) from err
            raise UpdateFailed(
                f"Realdata fetch HTTP error {err.status}: {err.message}"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Realdata fetch failed: {err}") from err

        # Some portal builds signal session expiry inside the JSON
        code = raw.get("code")
        if code in (401, 403, "401", "403"):
            self._session_age = 0.0
            raise UpdateFailed("Portal reports session invalid – will re-login on next poll")

        return raw

    # ------------------------------------------------------------------
    # Response normalisation
    # ------------------------------------------------------------------

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Extract all parXX keys from the response into {par_id: float_value}.

        Confirmed live response shape (flat, top-level):
          {"isNewRecord": true, "mn": 99999, "devid": 1,
           "par1": 2.0, "par2": 0.0, "par3": 0.0, ...}

        Non-parXX keys other than housekeeping fields are logged ONCE so we
        can discover unknown payload fields (e.g. an operating-mode flag
        outside the parXX namespace).
        """
        import re
        par_pattern = re.compile(r"^par\d+$")

        result: dict[str, Any] = {
            k: _safe_float(v)
            for k, v in raw.items()
            if par_pattern.match(str(k))
        }

        if not result:
            raise UpdateFailed(
                "No parXX keys found in realdata response. "
                f"Top-level keys: {list(raw.keys())[:10]}. "
                "Please open a GitHub issue with your portal's response structure."
            )

        # ── One-shot diagnostic logging of non-parXX keys ────────────────
        # Helps the user identify whether the portal sends a separate
        # "mode" / "status" field that we could use to determine the actual
        # heat-pump mode (Heizen / Brauchwasser / Entfrosten).
        if not getattr(self, "_logged_non_par_keys", False):
            housekeeping = {"isNewRecord", "mn", "devid", "id"}
            extras = {
                k: v for k, v in raw.items()
                if not par_pattern.match(str(k)) and k not in housekeeping
            }
            if extras:
                _LOGGER.info(
                    "ES Heatpump: non-parXX response keys (diagnostic, "
                    "logged once per session): %s",
                    extras,
                )
            self._logged_non_par_keys = True

        # ── Pass non-par keys through under a reserved namespace so
        # downstream sensors can read them without breaking the parXX schema
        result["_raw_meta"] = {
            k: v for k, v in raw.items() if not par_pattern.match(str(k))
        }

        _LOGGER.debug("ES Heatpump: received %d sensor values from portal", len(result) - 1)
        return result


    # ------------------------------------------------------------------
    # Konfiguration lesen und schreiben (Portal-Seite "setdata")
    # ------------------------------------------------------------------
    #
    # ACHTUNG: eigener parXX-Namensraum. /a/amt/setdata/get liefert par1 =
    # "Anlage ein/aus", waehrend par1 in /a/amt/realdata/get die aktuelle
    # Betriebsart ist. Die beiden Saetze duerfen nie vermischt werden - siehe
    # den Kopf von settings.py.

    async def _async_sicherstellen_angemeldet(self) -> None:
        if self._session_age == 0.0 or self._session_expired():
            await self._login()
        if self._mn is None:
            await self._discover_device()

    async def async_lies_konfiguration(self) -> dict[str, float]:
        """Liest den vollstaendigen Konfigurationsstand (rund 300 Werte).

        Das ist die Grundlage sowohl fuer die Bedien-Entities als auch fuer
        jede Sicherung. Bewusst wird *alles* gelesen, nicht nur die 74
        bedienbaren Felder: Was eine Sicherung nicht enthaelt, kann sie
        spaeter auch nicht zeigen.
        """
        await self._async_sicherstellen_angemeldet()

        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}{SETDATA_READ_PATH}"
        try:
            async with asyncio.timeout(25):
                resp = await session.post(
                    url,
                    data={"mn": self._mn, "devid": self._devid},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                resp.raise_for_status()
                raw: dict = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                self._session_age = 0.0
            raise UpdateFailed(
                f"Konfiguration konnte nicht gelesen werden (HTTP {err.status})"
            ) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Konfiguration konnte nicht gelesen werden: {err}") from err

        import re as _re
        muster = _re.compile(r"^par\d+$")
        werte = {k: _safe_float(v) for k, v in raw.items() if muster.match(str(k))}
        werte = {k: v for k, v in werte.items() if v is not None}
        if not werte:
            raise UpdateFailed(
                "Die Konfigurationsantwort enthaelt keine parXX-Felder. "
                f"Vorhandene Schluessel: {list(raw.keys())[:10]}"
            )
        # Die Satz-Kennung braucht der Schreibaufruf mit.
        self._setdata_id = str(raw.get("id") or "")
        return werte

    async def async_lies_stammdaten_kopf(self) -> None:
        """Holt Installateur-Klartext und Artikelnummer aus dem Formularkopf.

        Nur einmal je Sitzung - die Seite ist 70 kB gross, und die beiden
        Angaben aendern sich nie.
        """
        if self._kopf_gelesen:
            return
        self._kopf_gelesen = True   # auch bei Fehlschlag nicht erneut versuchen

        await self._async_sicherstellen_angemeldet()
        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}{SETDATA_FORM_PATH}?mn={self._mn}&devid={self._devid}"
        try:
            async with asyncio.timeout(30):
                resp = await session.get(url)
                resp.raise_for_status()
                text = await resp.text()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ES Heatpump: Formularkopf nicht lesbar: %s", err)
            return
        try:
            self.stammdaten = aus_formularkopf(text, self.stammdaten)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ES Heatpump: Formularkopf nicht auswertbar: %s", err)

    async def async_schreibe_konfiguration(self, par: str, wert: int) -> None:
        """Setzt genau einen Konfigurationswert in der Waermepumpe.

        Das Portal kennt keinen Sammelauftrag - jeder Wert geht einzeln, so
        wie es auch der "Setting parameters"-Knopf neben jedem Feld tut.

        Geprueft wird **vor** dem Senden gegen den Katalog: Wertebereich,
        erlaubte Auswahl, Schreibbarkeit. Das ist die letzte Stelle, an der
        ein falscher Wert noch aufzuhalten ist; danach steht er in der Anlage.
        """
        eintrag = SETTINGS.get(par)
        if eintrag is None:
            raise ValueError(
                f"{par} steht nicht im Katalog der bedienbaren Einstellungen."
            )
        geprueft = eintrag.validate(wert)

        await self._async_sicherstellen_angemeldet()

        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}{SETDATA_WRITE_PATH}"
        payload = {
            "id": getattr(self, "_setdata_id", "") or "",
            "mn": self._mn,
            "devid": self._devid,
            par: str(geprueft),
            "fieldName": par,
            "fieldValue": str(geprueft),
        }

        _LOGGER.info(
            "ES Heatpump: setze %s (%s) auf %s", par, eintrag.name, geprueft
        )
        try:
            async with asyncio.timeout(30):
                resp = await session.post(
                    url,
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                resp.raise_for_status()
                antwort: dict = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                self._session_age = 0.0
            raise UpdateFailed(
                f"Schreiben von {par} abgelehnt (HTTP {err.status})"
            ) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Schreiben von {par} fehlgeschlagen: {err}") from err

        # jeesite antwortet mit {"result": "true"/"false", "message": "..."}
        ergebnis = str(antwort.get("result", "")).lower()
        meldung = str(antwort.get("message") or antwort.get("msg") or "").strip()
        if ergebnis in ("false", "0") or "fail" in meldung.lower():
            raise UpdateFailed(
                f"Das Portal hat {par} = {geprueft} nicht angenommen: "
                f"{meldung or antwort}"
            )
        _LOGGER.debug("ES Heatpump: Portal bestaetigt %s: %s", par, meldung or antwort)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Main poll loop: login → discover device → fetch sensor data."""
        if self._session_age == 0.0 or self._session_expired():
            await self._login()

        if self._mn is None:
            await self._discover_device()

        raw = await self._fetch_realdata()
        return self._normalize(raw)

    async def async_validate_credentials(self) -> bool:
        """
        Validate credentials during config flow setup.
        Raises ConfigEntryAuthFailed on bad credentials.
        Raises UpdateFailed on network/portal errors.
        """
        await self._login()
        await self._discover_device()
        await self._fetch_realdata()
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
