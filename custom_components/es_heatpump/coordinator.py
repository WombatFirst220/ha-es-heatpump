"""Data coordinator for ES Heatpump integration."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEVICE_LIST_PATH,
    LOGIN_PATH,
    REALDATA_PATH,
    SETDATA_READ_PATH,
    SETDATA_WRITE_PATH,
    SETDATA_FORM_PATH,
    DOMAIN,
)
from .metadata import Stammdaten, aus_formularkopf, aus_geraeteliste
from .portal import (
    LOGIN_ABGELEHNT,
    LOGIN_OK,
    PAR_MUSTER,
    SitzungAbgelaufen,
    UnerwarteteAntwort,
    antwort_auswerten,
    login_einordnen,
)
from .settings import SETTINGS

_LOGGER = logging.getLogger(__name__)

# Force re-login after this many seconds (portal session timeout ~60 min)
SESSION_TTL = 3300  # 55 minutes – slightly under portal timeout

_XHR = {"X-Requested-With": "XMLHttpRequest"}


def _b64(value: str) -> str:
    """Base64-encode a string, as required by the myheatpump.com login API."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def eigene_clientsession(
    hass: HomeAssistant, *, auto_cleanup: bool = True
) -> aiohttp.ClientSession:
    """Eine ClientSession mit eigenem Cookie-Speicher.

    Bis v4.0.0 lief alles ueber ``async_get_clientsession(hass)`` - die von
    ganz Home Assistant geteilte Sitzung. Deren Cookie-Speicher enthielt dann
    *eine* JSESSIONID fuer myheatpump.com, die sich alle Eintraege und der
    Einrichtungsdialog teilten: Ein zweites Konto oder ein Test im Dialog hat
    die Anmeldung des ersten still ueberschrieben.

    ``unsafe=True`` laesst Cookies auch fuer eine als IP-Adresse eingetragene
    Portal-URL zu (eigene Portal-URL im Abschnitt "Verbindung").
    """
    return async_create_clientsession(
        hass,
        auto_cleanup=auto_cleanup,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )


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

    Seit v4.0.1 hat jeder Koordinator eine eigene HTTP-Sitzung (eigener
    Cookie-Speicher), Anmeldung und Geraetesuche laufen unter einer Sperre, und
    eine abgelaufene Sitzung wird sofort erkannt und einmal neu angemeldet.
    Der Einstellungs-Koordinator nutzt dieses Objekt als API und teilt damit
    dieselbe Sitzung.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        base_url: str,
        scan_interval: int,
        session: aiohttp.ClientSession | None = None,
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
        self._session = session if session is not None else eigene_clientsession(hass)
        self._session_age: float = 0.0
        # Zaehlt jede erfolgreiche Anmeldung. Wer eine abgelaufene Sitzung
        # meldet, nennt die Nummer, mit der er gefragt hat - so meldet sich
        # nicht jeder Koordinator einzeln neu an, wenn es einer schon getan hat.
        self._sitzung_nr: int = 0
        # Anmeldung + Geraetesuche duerfen nicht parallel laufen: Mess- und
        # Einstellungs-Koordinator starten mitunter gleichzeitig, und zwei
        # Logins ueberschreiben sich gegenseitig die JSESSIONID.
        self._anmelde_lock = asyncio.Lock()
        # Device identifiers discovered after login
        self._mn: str | None = None
        self._devid: str | None = None
        self._setdata_id: str = ""
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

    def _braucht_anmeldung(self) -> bool:
        return self._session_age == 0.0 or self._session_expired()

    def _sitzung_verwerfen(self, nr: int) -> None:
        """Markiert die Sitzung ``nr`` als ungueltig (falls noch die aktuelle)."""
        if nr == self._sitzung_nr:
            self._session_age = 0.0

    async def _async_sicherstellen_angemeldet(self) -> None:
        """Anmelden und Geraet suchen, falls noetig - unter der Sperre.

        Nach Erhalt der Sperre wird erneut geprueft: Hat der andere
        Koordinator sich in der Zwischenzeit angemeldet, bleibt es dabei.
        """
        if not self._braucht_anmeldung() and self._mn is not None:
            return
        async with self._anmelde_lock:
            if self._braucht_anmeldung():
                await self._login()
            if self._mn is None:
                try:
                    await self._discover_device()
                except UpdateFailed:
                    # Kam statt der Geraeteliste die Anmeldeseite, hilft nur
                    # eine neue Anmeldung - beim naechsten Versuch, nicht hier
                    # (hoechstens eine Anmeldung je Aufruf).
                    self._session_age = 0.0
                    raise

    # ------------------------------------------------------------------
    # Step 1 – Login
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """
        Authenticate against myheatpump.com.
        Credentials must be Base64-encoded in the POST body.
        On success the server sets JSESSIONID + heatpump.session.id cookies,
        which this coordinator's own CookieJar carries on all subsequent requests.

        Nur eine eindeutige Ablehnung der Zugangsdaten loest
        ``ConfigEntryAuthFailed`` (und damit die erneute Anmeldung im
        Einrichtungsdialog) aus. Wartung, Captcha, Netzfehler und unklare
        Antworten sind ``UpdateFailed`` - der naechste Abruf versucht es erneut.
        """
        login_url = f"{self._base_url}{LOGIN_PATH}"

        payload = {
            "username":       _b64(self._username),
            "password":       _b64(self._password),
            "validCode":      "",   # CAPTCHA – not required for API access
            "loginValidCode": "",
            "__url":          "",
        }

        _LOGGER.debug("ES Heatpump: authenticating as %s", self._username)

        # Alte, womoeglich abgelaufene Sitzungs-Cookies nicht mitschicken.
        try:
            self._session.cookie_jar.clear()
        except Exception:  # noqa: BLE001
            pass

        try:
            async with asyncio.timeout(20):
                async with self._session.post(
                    login_url,
                    data=payload,
                    headers=_XHR,
                    allow_redirects=False,
                ) as resp:
                    resp.raise_for_status()
                    text = await resp.text()

        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise ConfigEntryAuthFailed(
                    f"Login rejected (HTTP {err.status}) for {self._username}"
                ) from err
            raise UpdateFailed(f"Login HTTP error {err.status}: {err.message}") from err
        except Exception as err:
            raise UpdateFailed(f"Login request failed: {err}") from err

        try:
            result: Any = json.loads(text)
        except ValueError as err:
            raise UpdateFailed(
                "Login: Portal antwortet nicht mit JSON (Wartung?): "
                f"{text.strip()[:120]!r}"
            ) from err

        einordnung = login_einordnen(result)
        if einordnung != LOGIN_OK:
            if isinstance(result, dict):
                raw_msg = result.get("msg") or result.get("message") or str(result)
            else:
                raw_msg = str(result)[:200]
            if einordnung == LOGIN_ABGELEHNT:
                _LOGGER.error("ES Heatpump: login failed – portal says: %s", raw_msg)
                raise ConfigEntryAuthFailed(
                    f"Login rejected by portal for {self._username}: {raw_msg}"
                )
            raise UpdateFailed(f"Login nicht bestaetigt, Portal meldet: {raw_msg}")

        self._session_age = time.monotonic()
        self._sitzung_nr += 1
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
        list_url = f"{self._base_url}{DEVICE_LIST_PATH}"

        try:
            async with asyncio.timeout(20):
                async with self._session.post(list_url, data={}, headers=_XHR) as resp:
                    resp.raise_for_status()
                    text = await resp.text()
            result: Any = json.loads(text)
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
        if not isinstance(first, dict):
            raise UpdateFailed(
                f"Unerwarteter Geraeteeintrag ({type(first).__name__}) in der "
                "Geraeteliste. Please open a GitHub issue."
            )
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
            self._mn = None
            raise UpdateFailed(
                f"Could not find 'mn' field in device entry: {list(first.keys())}. "
                "Please open a GitHub issue."
            )

        _LOGGER.info(
            "ES Heatpump: discovered device  mn=%s  devid=%s",
            self._mn, self._devid,
        )

    # ------------------------------------------------------------------
    # Gemeinsamer Abruf mit Sitzungspruefung
    # ------------------------------------------------------------------

    async def _post_einmal(
        self, url: str, daten: dict[str, Any], zeitlimit: float, erwarte_parameter: bool
    ) -> dict[str, Any]:
        """Ein POST, ausgewertet ueber ``portal.antwort_auswerten``."""
        try:
            async with asyncio.timeout(zeitlimit):
                async with self._session.post(url, data=daten, headers=_XHR) as resp:
                    if resp.status in (401, 403):
                        raise SitzungAbgelaufen(f"HTTP {resp.status}")
                    resp.raise_for_status()
                    text = await resp.text()
                    content_type = resp.headers.get("Content-Type", "")
        except SitzungAbgelaufen:
            raise
        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"HTTP-Fehler {err.status}: {err.message}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Anfrage fehlgeschlagen: {err}") from err
        try:
            return antwort_auswerten(
                text, content_type, erwarte_parameter=erwarte_parameter
            )
        except UnerwarteteAntwort as err:
            raise UpdateFailed(f"Unerwartete Antwort des Portals: {err}") from err

    async def _post_mit_sitzung(
        self,
        pfad: str,
        *,
        zeitlimit: float = 20,
        erwarte_parameter: bool = True,
        zusatz: dict[str, Any] | None = None,
        was: str = "Abruf",
    ) -> dict[str, Any]:
        """POST mit mn/devid; bei abgelaufener Sitzung einmal neu anmelden.

        Bis v4.0.0 blieb eine vom Portal verworfene Sitzung (HTML-Umleitung
        auf die Anmeldeseite, leere JSON-Antwort) bis zum Ablauf von
        SESSION_TTL bestehen - so lange scheiterte jeder Abruf.
        """
        url = f"{self._base_url}{pfad}"
        for versuch in (1, 2):
            await self._async_sicherstellen_angemeldet()
            nr = self._sitzung_nr
            daten: dict[str, Any] = {"mn": self._mn, "devid": self._devid}
            if zusatz:
                daten.update(zusatz)
            try:
                return await self._post_einmal(url, daten, zeitlimit, erwarte_parameter)
            except SitzungAbgelaufen as err:
                self._sitzung_verwerfen(nr)
                if versuch == 2:
                    raise UpdateFailed(
                        f"{was}: Sitzung auch nach erneuter Anmeldung ungueltig ({err})"
                    ) from err
                _LOGGER.debug(
                    "ES Heatpump: %s - Sitzung abgelaufen (%s), melde neu an", was, err
                )
        raise UpdateFailed(f"{was} fehlgeschlagen")  # pragma: no cover

    # ------------------------------------------------------------------
    # Step 3 – Sensor data
    # ------------------------------------------------------------------

    async def _fetch_realdata(self) -> dict[str, Any]:
        """
        POST /a/amt/realdata/get  with  mn=XXXX&devid=X.
        Returns the raw JSON dict from the portal.
        """
        return await self._post_mit_sitzung(REALDATA_PATH, was="Messwerte")

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
        if not isinstance(raw, dict):
            raise UpdateFailed(
                f"Unerwartete Messwert-Antwort ({type(raw).__name__} statt Objekt)"
            )
        par_pattern = PAR_MUSTER

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

    async def async_lies_konfiguration(self) -> dict[str, float]:
        """Liest den vollstaendigen Konfigurationsstand (rund 300 Werte).

        Das ist die Grundlage sowohl fuer die Bedien-Entities als auch fuer
        jede Sicherung. Bewusst wird *alles* gelesen, nicht nur die 74
        bedienbaren Felder: Was eine Sicherung nicht enthaelt, kann sie
        spaeter auch nicht zeigen.
        """
        try:
            raw = await self._post_mit_sitzung(
                SETDATA_READ_PATH, zeitlimit=25, was="Konfiguration"
            )
        except UpdateFailed as err:
            raise UpdateFailed(f"Konfiguration konnte nicht gelesen werden: {err}") from err

        werte = {k: _safe_float(v) for k, v in raw.items() if PAR_MUSTER.match(str(k))}
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
        Angaben aendern sich nie. Als gelesen gilt der Kopf erst, wenn die
        Seite tatsaechlich geladen wurde (bis v4.0.0 wurde die Marke schon vor
        der Anmeldung gesetzt; ein einziger Fehlschlag verhinderte jeden
        weiteren Versuch).
        """
        if self._kopf_gelesen:
            return

        try:
            await self._async_sicherstellen_angemeldet()
        except UpdateFailed as err:
            _LOGGER.debug("ES Heatpump: Formularkopf - Anmeldung fehlgeschlagen: %s", err)
            return
        url = f"{self._base_url}{SETDATA_FORM_PATH}?mn={self._mn}&devid={self._devid}"
        try:
            async with asyncio.timeout(30):
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    text = await resp.text()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ES Heatpump: Formularkopf nicht lesbar: %s", err)
            return
        # Erfolgreich geladen: auch wenn die Auswertung scheitert, hilft ein
        # erneuter Abruf derselben Seite nicht weiter.
        self._kopf_gelesen = True
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

        Fehler kommen als ``HomeAssistantError`` (nicht ``UpdateFailed``),
        damit die Oberflaeche die Meldung anzeigt statt "Unbekannter Fehler".
        """
        eintrag = SETTINGS.get(par)
        if eintrag is None:
            raise ValueError(
                f"{par} steht nicht im Katalog der bedienbaren Einstellungen."
            )
        geprueft = eintrag.validate(wert)

        zusatz = {
            "id": self._setdata_id or "",
            par: str(geprueft),
            "fieldName": par,
            "fieldValue": str(geprueft),
        }

        _LOGGER.info(
            "ES Heatpump: setze %s (%s) auf %s", par, eintrag.name, geprueft
        )
        # Ein Wiederholen nach erneuter Anmeldung ist hier unbedenklich: Kam
        # die Anmeldeseite zurueck, hat das Portal den Wert nicht angenommen,
        # und "setze par auf X" zweimal ergibt denselben Stand.
        try:
            antwort = await self._post_mit_sitzung(
                SETDATA_WRITE_PATH,
                zeitlimit=30,
                erwarte_parameter=False,
                zusatz=zusatz,
                was=f"Schreiben von {par}",
            )
        except UpdateFailed as err:
            raise HomeAssistantError(
                f"Schreiben von {par} fehlgeschlagen: {err}"
            ) from err

        # jeesite antwortet mit {"result": "true"/"false", "message": "..."}
        ergebnis = str(antwort.get("result", "")).lower()
        meldung = str(antwort.get("message") or antwort.get("msg") or "").strip()
        if ergebnis in ("false", "0") or "fail" in meldung.lower():
            raise HomeAssistantError(
                f"Das Portal hat {par} = {geprueft} nicht angenommen: "
                f"{meldung or antwort}"
            )
        _LOGGER.debug("ES Heatpump: Portal bestaetigt %s: %s", par, meldung or antwort)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Main poll loop: login → discover device → fetch sensor data."""
        raw = await self._fetch_realdata()
        return self._normalize(raw)

    async def async_validate_credentials(self) -> bool:
        """
        Validate credentials during config flow setup.
        Raises ConfigEntryAuthFailed on bad credentials.
        Raises UpdateFailed on network/portal errors.
        """
        await self._async_sicherstellen_angemeldet()
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
