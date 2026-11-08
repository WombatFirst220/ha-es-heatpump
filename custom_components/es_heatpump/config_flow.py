"""Config flow for ES Heatpump integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

try:  # Abschnitte im Formular gibt es seit HA 2024.7
    from homeassistant.data_entry_flow import section
except ImportError:  # pragma: no cover
    section = None
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_BACKUP_INTERVAL,
    CONF_BACKUP_KEEP,
    CONF_DASHBOARD_DESIGN,
    CONF_ENABLE_WRITES,
    CONF_HYDRAULIC_CARD,
    DEFAULT_DASHBOARD_DESIGN,
    DEFAULT_HYDRAULIC_CARD,
    DESIGN_OPTIONS,
    CONF_SETTINGS_INTERVAL,
    DEFAULT_BACKUP_INTERVAL,
    DEFAULT_BACKUP_KEEP,
    DEFAULT_ENABLE_WRITES,
    DEFAULT_SETTINGS_INTERVAL,
    CONF_BASE_URL,
    CONF_FLOW_RATE,
    CONF_FLOW_RATE_DHW,
    CONF_MODE_SOURCE,
    CONF_DHW_MARGIN_K,
    CONF_FLOW_ENTITY,
    CONF_MODEL,
    CONF_POWER_ENTITY,
    CONF_ENERGY_ENTITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_FLOW_RATE,
    DEFAULT_FLOW_RATE_DHW,
    DEFAULT_DHW_MARGIN_K,
    MODEL_UNKNOWN,
    NOMINAL_FLOW_RATES_M3H,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KNOWN_BASE_URLS,
)


def _flow_rate_selector() -> NumberSelector:
    """Numeric input for a flow-rate value in m³/h."""
    return NumberSelector(
        NumberSelectorConfig(
            min=0.01, max=10.0, step=0.01, mode=NumberSelectorMode.BOX,
            unit_of_measurement="m³/h",
        )
    )


def _model_selector() -> SelectSelector:
    """Pick the unit so the datasheet nominal flow can be filled in."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(NOMINAL_FLOW_RATES_M3H) + [MODEL_UNKNOWN],
            # Optionsfelder statt Dropdown: Das Dropdown liess den Dialog auf
            # dem iPhone nach oben springen (v3.1.1).
            mode=SelectSelectorMode.LIST,
        )
    )


def _dhw_margin_selector() -> NumberSelector:
    """Vorlauf-ueber-Soll threshold that separates DHW from heating."""
    return NumberSelector(
        NumberSelectorConfig(
            min=2.0, max=25.0, step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="K",
        )
    )


def _design_selector() -> SelectSelector:
    """Look of the bundled dashboard (v3.1.0)."""
    return SelectSelector(
        SelectSelectorConfig(
            options=DESIGN_OPTIONS,
            mode=SelectSelectorMode.LIST,
            translation_key=CONF_DASHBOARD_DESIGN,
        )
    )


def _base_url_selector() -> SelectSelector:
    """Dropdown of known myheatpump.com regional portals, allowing custom values."""
    return SelectSelector(
        SelectSelectorConfig(
            options=KNOWN_BASE_URLS,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )
from .coordinator import ESHeatpumpCoordinator, eigene_clientsession

_LOGGER = logging.getLogger(__name__)


async def _async_pruefe_zugang(
    hass, benutzer: str, passwort: str, base_url: str
) -> str | None:
    """Prueft Zugangsdaten gegen das Portal; liefert den Fehlerschluessel.

    Eigene, danach wieder geloeste HTTP-Sitzung: Bis v4.0.0 lief die Pruefung
    ueber die von ganz Home Assistant geteilte Sitzung und ueberschrieb dabei
    die JSESSIONID eines bereits laufenden Eintrags.
    """
    session = eigene_clientsession(hass, auto_cleanup=False)
    try:
        coordinator = ESHeatpumpCoordinator(
            hass=hass,
            username=benutzer,
            password=passwort,
            base_url=base_url or DEFAULT_BASE_URL,
            scan_interval=DEFAULT_SCAN_INTERVAL,
            session=session,
        )
        await coordinator.async_validate_credentials()
    except ConfigEntryAuthFailed:
        return "invalid_auth"
    except UpdateFailed:
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error during ES Heatpump setup")
        return "unknown"
    finally:
        # detach() statt close(): Der Connector gehoert Home Assistant.
        session.detach()
    return None


class ESHeatpumpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            fehler = await _async_pruefe_zugang(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            )
            if fehler:
                errors["base"] = fehler
            else:
                return self.async_create_entry(
                    title=f"ES Heatpump ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_BASE_URL, default=DEFAULT_BASE_URL
                ): _base_url_selector(),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=10, max=3600)),
                vol.Optional(CONF_POWER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_ENERGY_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="energy")
                ),
                vol.Optional(CONF_MODE_SOURCE): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_FLOW_RATE, default=DEFAULT_FLOW_RATE
                ): _flow_rate_selector(),
                vol.Optional(
                    CONF_FLOW_RATE_DHW, default=DEFAULT_FLOW_RATE_DHW
                ): _flow_rate_selector(),
                vol.Optional(
                    CONF_DHW_MARGIN_K, default=DEFAULT_DHW_MARGIN_K
                ): _dhw_margin_selector(),
                vol.Optional(CONF_MODEL, default=MODEL_UNKNOWN): _model_selector(),
                vol.Optional(CONF_FLOW_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # ── Erneute Anmeldung (v4.0.1) ───────────────────────────────────────
    # Lehnt das Portal die Zugangsdaten ab, wirft der Koordinator
    # ConfigEntryAuthFailed; Home Assistant startet dann diesen Schritt. Bis
    # v4.0.0 fehlte er - die Integration blieb nach einer Passwortaenderung
    # im Portal dauerhaft tot. Der Benutzername bleibt fest (er ist die
    # unique_id des Eintrags), nur das Passwort wird neu abgefragt.

    def _reauth_eintrag(self) -> config_entries.ConfigEntry | None:
        holen = getattr(self, "_get_reauth_entry", None)   # ab HA 2024.11
        if holen is not None:
            try:
                return holen()
            except Exception:  # noqa: BLE001
                pass
        return self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", "")
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        eintrag = self._reauth_eintrag()
        if eintrag is None:  # pragma: no cover - Eintrag inzwischen geloescht
            return self.async_abort(reason="reauth_successful")
        benutzer = eintrag.data[CONF_USERNAME]

        if user_input is not None:
            basis = eintrag.options.get(
                CONF_BASE_URL, eintrag.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            ) or DEFAULT_BASE_URL
            fehler = await _async_pruefe_zugang(
                self.hass, benutzer, user_input[CONF_PASSWORD], basis
            )
            if fehler:
                errors["base"] = fehler
            else:
                neu = {**eintrag.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                aktualisieren = getattr(self, "async_update_reload_and_abort", None)
                # Bis HA 2024.x laedt async_update_reload_and_abort nur bei
                # geaenderten Daten neu - bei unveraendertem Passwort (das
                # Portal hatte es nur voruebergehend abgelehnt) haendisch.
                if aktualisieren is not None and neu != dict(eintrag.data):
                    return aktualisieren(
                        eintrag, data=neu, reason="reauth_successful"
                    )
                self.hass.config_entries.async_update_entry(eintrag, data=neu)
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(eintrag.entry_id)
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": benutzer},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ESHeatpumpOptionsFlow":
        return ESHeatpumpOptionsFlow(config_entry)


# ── Abschnitte des Einstellungsdialogs (v3.1.1) ─────────────────────────────
# Gruppiert statt einer langen Liste; die Erklärungen stehen als Hilfetext
# (data_description) unter dem Feld, nicht mehr in der Beschriftung.  Lange
# Beschriftungen liefen in die Eingabefelder hinein.
SEC_MESSUNG    = "messung"
SEC_DASHBOARD  = "dashboard"
SEC_ZUGRIFF    = "zugriff"
SEC_VERBINDUNG = "verbindung"

# (Abschnitt, eingeklappt)
OPTION_SECTIONS: list[tuple[str, bool]] = [
    (SEC_MESSUNG, False),
    (SEC_DASHBOARD, False),
    (SEC_ZUGRIFF, True),
    (SEC_VERBINDUNG, True),
]

_ENTITY_KEYS = (CONF_POWER_ENTITY, CONF_ENERGY_ENTITY, CONF_MODE_SOURCE, CONF_FLOW_ENTITY)


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Abschnitte auflösen: {"messung": {...}, ...} → flaches Options-Dict."""
    flach: dict[str, Any] = {}
    for key, wert in user_input.items():
        if key in dict(OPTION_SECTIONS) and isinstance(wert, dict):
            flach.update(wert)
        else:
            flach[key] = wert
    return flach


class ESHeatpumpOptionsFlow(config_entries.OptionsFlow):
    """Allow changing scan interval, base URL, power entity, flow rate."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    def _wert(self, key: str, standard: Any = None) -> Any:
        opts = self._config_entry.options
        return opts.get(key, self._config_entry.data.get(key, standard))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            user_input = _flatten(user_input)

            # Leere Entity-Felder AUSDRUECKLICH als "" ablegen, nicht verwerfen.
            # Wuerde der Schluessel fehlen, faende `opts.get(key, data.get(key))`
            # den bei der Einrichtung gesetzten Wert in entry.data wieder - eine
            # einmal gewaehlte Entity liesse sich dann nie mehr entfernen,
            # sondern nur ersetzen (Fehler bis v2.3.0).
            for key in _ENTITY_KEYS:
                if user_input.get(key) in (None, ""):
                    user_input[key] = ""

            # Modellwahl setzt den Volumenstrom auf den Nennwert des Datenblatts,
            # sobald sich das Modell geaendert hat. Danach bleibt der Wert von
            # Hand anpassbar.
            modell = user_input.get(CONF_MODEL)
            vorher = self._wert(CONF_MODEL)
            if modell and modell != vorher and modell in NOMINAL_FLOW_RATES_M3H:
                user_input[CONF_FLOW_RATE] = NOMINAL_FLOW_RATES_M3H[modell][1]
                _LOGGER.info(
                    "ES Heatpump: Modell %s gewaehlt, Volumenstrom auf den "
                    "Nennwert %.2f m3/h gesetzt.",
                    modell, NOMINAL_FLOW_RATES_M3H[modell][1],
                )

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        w = self._wert

        def entity(key: str, **cfg: Any) -> tuple[vol.Optional, EntitySelector]:
            # WICHTIG: description={"suggested_value": ...} statt default=.
            # vol.Optional(key, default=X) setzt X ein, sobald der Schluessel
            # fehlt - ein geleertes Feld kaeme im Handler also nie als leer an,
            # und die Entity liesse sich nur ersetzen, nie entfernen (Fehler bis
            # v2.4.0). suggested_value fuellt das Feld vor, ohne beim Weglassen
            # etwas einzusetzen.
            return (
                vol.Optional(key, description={"suggested_value": w(key) or None}),
                EntitySelector(EntitySelectorConfig(domain="sensor", **cfg)),
            )

        felder: dict[str, dict] = {
            SEC_MESSUNG: dict([
                (vol.Optional(CONF_MODEL, default=w(CONF_MODEL, MODEL_UNKNOWN)),
                 _model_selector()),
                (vol.Optional(CONF_FLOW_RATE, default=w(CONF_FLOW_RATE, DEFAULT_FLOW_RATE)),
                 _flow_rate_selector()),
                (vol.Optional(CONF_FLOW_RATE_DHW,
                              default=w(CONF_FLOW_RATE_DHW, DEFAULT_FLOW_RATE_DHW)),
                 _flow_rate_selector()),
                entity(CONF_POWER_ENTITY, device_class="power"),
                entity(CONF_ENERGY_ENTITY, device_class="energy"),
                entity(CONF_FLOW_ENTITY),
                (vol.Optional(CONF_DHW_MARGIN_K,
                              default=w(CONF_DHW_MARGIN_K, DEFAULT_DHW_MARGIN_K)),
                 _dhw_margin_selector()),
                entity(CONF_MODE_SOURCE),
            ]),
            SEC_DASHBOARD: {
                vol.Optional(CONF_HYDRAULIC_CARD,
                             default=w(CONF_HYDRAULIC_CARD, DEFAULT_HYDRAULIC_CARD)): bool,
                vol.Optional(CONF_DASHBOARD_DESIGN,
                             default=w(CONF_DASHBOARD_DESIGN, DEFAULT_DASHBOARD_DESIGN)):
                    _design_selector(),
            },
            # Schreiben ist standardmaessig AUS. Eine Cloud-Integration, die
            # ungefragt in eine Heizung schreiben darf, ist eine andere Art von
            # Software als eine, die nur liest.
            SEC_ZUGRIFF: {
                vol.Optional(CONF_ENABLE_WRITES,
                             default=w(CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES)): bool,
                vol.Optional(CONF_SETTINGS_INTERVAL,
                             default=w(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                vol.Optional(CONF_BACKUP_INTERVAL,
                             default=w(CONF_BACKUP_INTERVAL, DEFAULT_BACKUP_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
                vol.Optional(CONF_BACKUP_KEEP,
                             default=w(CONF_BACKUP_KEEP, DEFAULT_BACKUP_KEEP)):
                    vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
            },
            SEC_VERBINDUNG: {
                vol.Optional(CONF_BASE_URL, default=w(CONF_BASE_URL, DEFAULT_BASE_URL)):
                    _base_url_selector(),
                vol.Optional(CONF_SCAN_INTERVAL,
                             default=w(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            },
        }

        if section is None:  # HA vor 2024.7: flach wie bisher
            flach: dict = {}
            for teil in felder.values():
                flach.update(teil)
            return vol.Schema(flach)

        return vol.Schema({
            vol.Required(name): section(vol.Schema(felder[name]), {"collapsed": zu})
            for name, zu in OPTION_SECTIONS
        })
