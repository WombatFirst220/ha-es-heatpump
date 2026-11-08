"""
dashboard_layout.py
───────────────────
Passt die mitgelieferte Dashboard-Konfiguration an die Optionen an (v3.1.0):

  * **Hydraulik-Schema** – setzt die Heat Pump Hydraulic Card
    (Sturmi77/heatpump-hydraulic-card, MIT, mitgeliefert unter ``www/``) als
    erste Karte in die Übersicht.
  * **Design** – ``origami`` ersetzt die Ansichten durch einen eigenen
    Abschnitts-Aufbau (``origami_ansichten``) und setzt das Theme „Origami“
    als View-Theme. Andere Dashboards und das Benutzer-Theme bleiben
    unberührt.

Ohne Home-Assistant-Abhängigkeit, damit es sich ohne HA testen lässt.
"""
from __future__ import annotations

import copy
from typing import Any

from .const import DESIGN_ORIGAMI, ORIGAMI_THEME_NAME

HYDRAULIC_CARD_TYPE = "custom:heatpump-hydraulic-card"
# Auswertungskarte der Integration (www/es-heatpump-analysis-card.js, v4.0.0)
ANALYSIS_CARD_TYPE = "custom:es-heatpump-analysis-card"

# Betriebsart der Integration → Modus der Karte.  Die Karte kennt off, heating,
# dhw, cooling, defrost, idle.  Kombinierte Zustände zeigen Warmwasser, weil das
# Umschaltventil dann zum Speicher steht.  Schlüssel sind seit GitHub-Issue #6
# die Zustands-Schlüssel der Entity (const.BETRIEBSART_STATE_KEYS), nicht mehr
# die deutschen Texte.
MODE_MAP: dict[str, str] = {
    "off": "off",
    "heating": "heating",
    "dhw": "dhw",
    "dhw_heating": "dhw",
    "cooling": "cooling",
    "dhw_cooling": "dhw",
    "defrost": "defrost",
    "unknown": "idle",
}


def hydraulik_karte() -> dict[str, Any]:
    """Kartenkonfiguration für das Energy-Save-Schema.

    Es gibt kein Preset für Energy Save, deshalb eine feste Zuordnung auf die
    ``es_hp_*``-Entities.  Aufgebaut wie das Anlagenschaubild im Portal:
    Wärmepumpe → Umschaltventil → getrennter Warmwasserspeicher (TW) bzw.
    paralleler Pufferspeicher (TC) → Heizkreis.

    Bewusst nicht belegt:
      * ``hc_pump`` / Pumpen P0–P2 – standardmäßig deaktiviert; die Karte
        zeichnet stattdessen die Primärpumpe (``primary_pump``).
      * ``room`` – par11 ist der Fühler an der Wärmepumpe, nicht der Wohnraum.
      * ``controls`` – die Karte könnte Sollwerte direkt verstellen. Das
        Schreiben ist eine bewusste Entscheidung des Betreibers
        (``enable_writes``) und gehört nicht als Nebeneffekt aufs Schema.
    """
    return {
        "type": HYDRAULIC_CARD_TYPE,
        "title": "Hydraulik",
        "unit_style": "generic",
        "source_type": "air",
        "storage": "separate",
        "primary_pump": True,
        "compressor_speed_max": 90,
        "timeline": True,
        "timeline_hours": 24,
        "entities": {
            "mode": "sensor.es_hp_betriebsart",
            "compressor": "sensor.es_hp_frequenz_hz",
            "compressor_speed": "sensor.es_hp_frequenz_hz",
            "fan_speed": "sensor.es_hp_luefter_drehzahl",
            "power": "sensor.es_hp_leistung_elektrisch",
            "heat": "sensor.es_hp_thermische_leistung",
            "flow": "sensor.es_hp_vorlauf_tuo",
            "return": "sensor.es_hp_ruecklauf_tui",
            "outdoor": "sensor.es_hp_aussentemp_ta",
            "dhw_top": "sensor.es_hp_warmwasser_tw",
            "dhw_target": "number.es_hp_cfg_par55",
            "buffer_top": "sensor.es_hp_heizen",
            "hot_gas": "sensor.es_hp_heissgas_td",
            "suction_temp": "sensor.es_hp_sauggas_ts",
            "high_pressure": "sensor.es_hp_hochdruck_pd",
            "low_pressure": "sensor.es_hp_saugdruck_ps",
            "eev": "sensor.es_hp_ventil_oeffnung",
        },
        "mode_map": dict(MODE_MAP),
        "tiles": ["cop_live", "spread", "heat_live", "dhw_top", "outdoor"],
        "details": [
            {"entity": "sensor.es_hp_verdichter_strom", "name": "Verdichterstrom"},
            {"entity": "sensor.es_hp_lamellentauscher_tp", "name": "Lamellentauscher"},
            {"entity": "sensor.es_hp_spannung", "name": "Netzspannung"},
            {"entity": "sensor.es_hp_raumtemperatur", "name": "Raumfühler an der WP"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Origami-Ansichten (v3.2.0)
# ─────────────────────────────────────────────────────────────────────────────
# Origami ist ein Abschnitts-Dashboard fürs Handy: Überschriften, darunter
# Kacheln mit Symbol im runden Feld.  Hier nur mit Bordmitteln nachgebaut
# (heading, tile, history-graph, statistics-graph), damit außer dem Theme nichts
# nachinstalliert werden muss.  Braucht HA 2024.10 (Überschrift mit Badges).

HALB = {"columns": 6}
VOLL = {"columns": "full"}


def _kopf(titel: str, *badges: str, stil: str = "title") -> dict[str, Any]:
    karte: dict[str, Any] = {"type": "heading", "heading": titel, "heading_style": stil}
    if badges:
        karte["badges"] = [
            {"type": "entity", "entity": e, "show_state": True, "show_icon": True}
            for e in badges
        ]
    return karte


def _kachel(
    entity: str, name: str, icon: str | None = None, farbe: str | None = None,
) -> dict[str, Any]:
    # Namen kurz halten: Eine halbe Kachel fasst am Handy etwa 10 Zeichen.
    karte: dict[str, Any] = {
        "type": "tile", "entity": entity, "name": name,
        "vertical": False, "grid_options": HALB,
    }
    if icon:
        karte["icon"] = icon
    if farbe:
        # Origami definiert die HA-Farbnamen gedämpft, so passt das Symbol zum Theme.
        karte["color"] = farbe
    return karte


def _verlauf(titel: str, stunden: int, *reihen: tuple[str, str]) -> dict[str, Any]:
    return {
        "type": "history-graph", "title": titel, "hours_to_show": stunden,
        "grid_options": VOLL,
        "entities": [{"entity": e, "name": n} for e, n in reihen],
    }


def _abschnitt(*karten: dict[str, Any]) -> dict[str, Any]:
    return {"type": "grid", "cards": list(karten)}


def origami_ansichten(hydraulik: bool) -> list[dict[str, Any]]:
    """Die Ansichten im Origami-Aufbau (Pfade wie im Standard-Dashboard)."""
    # Die Betriebsart zeigt das Schema selbst ("Heizen · läuft"); ohne Schema
    # gehört sie in die Überschrift.
    wp_badges = ["sensor.es_hp_aktueller_cop", "sensor.es_hp_aussentemp_ta"]
    if not hydraulik:
        wp_badges.insert(0, "sensor.es_hp_betriebsart")
    wp = [_kopf("Wärmepumpe", *wp_badges)]
    if hydraulik:
        schema = hydraulik_karte()
        schema["title"] = ""               # "" blendet den Kartentitel aus, die Überschrift steht darüber
        schema["grid_options"] = VOLL
        wp.append(schema)

    uebersicht = [
        _abschnitt(*wp),
        _abschnitt(
            _kopf("Jetzt"),
            _kachel("sensor.es_hp_aktueller_cop", "COP", "mdi:gauge", "green"),
            _kachel("sensor.es_hp_thermische_leistung", "Wärme", "mdi:fire", "deep-orange"),
            _kachel("sensor.es_hp_leistung_elektrisch", "Strom", "mdi:lightning-bolt", "amber"),
            _kachel("sensor.es_hp_frequenz_hz", "Verdichter", "mdi:sine-wave", "indigo"),
            _kachel("sensor.es_hp_vorlauf_tuo", "Vorlauf", None, "red"),
            _kachel("sensor.es_hp_ruecklauf_tui", "Rücklauf", None, "blue"),
            _kachel("sensor.es_hp_spreizung", "Spreizung", "mdi:delta", "purple"),
            _kachel("sensor.es_hp_aussentemp_ta", "Außen", None, "cyan"),
        ),
        _abschnitt(
            _kopf("Speicher"),
            _kachel("sensor.es_hp_warmwasser_tw", "Warmwasser", None, "deep-orange"),
            _kachel("number.es_hp_cfg_par55", "WW Soll", "mdi:water-thermometer-outline", "orange"),
            _kachel("sensor.es_hp_heizen", "Puffer", None, "teal"),
            _kachel("sensor.es_hp_heizen_soll_manuell", "Heizen Soll", None, "orange"),
            _kachel("sensor.es_hp_heizen_soll", "Tup", None, "teal"),
            _kachel("sensor.es_hp_raumtemperatur", "WP-Fühler", None, "grey"),
        ),
        _abschnitt(
            _kopf("Verlauf · 24 h"),
            _verlauf("Vor- und Rücklauf", 24,
                     ("sensor.es_hp_vorlauf_tuo", "Vorlauf"),
                     ("sensor.es_hp_ruecklauf_tui", "Rücklauf")),
            _verlauf("Verdichter", 24, ("sensor.es_hp_frequenz_hz", "Frequenz")),
        ),
    ]

    energie = [
        _abschnitt(
            _kopf("Effizienz"),
            {
                "type": "statistics-graph", "title": "COP, Stundenmittel 7 Tage",
                "entities": [{"entity": "sensor.es_hp_aktueller_cop", "name": "COP"}],
                "chart_type": "line", "period": "hour", "days_to_show": 7,
                "stat_types": ["mean"], "grid_options": VOLL,
            },
        ),
        _abschnitt(
            _kopf("Leistung · 24 h"),
            _verlauf("Wärme und Strom", 24,
                     ("sensor.es_hp_thermische_leistung", "Wärme"),
                     ("sensor.es_hp_leistung_elektrisch", "Strom")),
            _verlauf("Heißgas", 24, ("sensor.es_hp_heissgas_td", "Heißgas Td")),
        ),
        _abschnitt(
            _kopf("Betriebsstunden"),
            _kachel("sensor.es_hp_ah_betriebszeit", "AH gesamt", None, "blue-grey"),
            _kachel("sensor.es_hp_hbh_betriebszeit", "HBH gesamt", None, "blue-grey"),
        ),
    ]

    diagnose = [
        _abschnitt(
            _kopf("Kältekreis"),
            _kachel("sensor.es_hp_heissgas_td", "Heißgas", None, "red"),
            _kachel("sensor.es_hp_sauggas_ts", "Sauggas", None, "light-blue"),
            _kachel("sensor.es_hp_hochdruck_pd", "Hochdruck", None, "red"),
            _kachel("sensor.es_hp_saugdruck_ps", "Saugdruck", None, "light-blue"),
            _kachel("sensor.es_hp_ventil_oeffnung", "EEV", None, "purple"),
            _kachel("sensor.es_hp_lamellentauscher_tp", "Lamellen", None, "cyan"),
        ),
        _abschnitt(
            _kopf("Elektrik und Lüfter"),
            _kachel("sensor.es_hp_verdichter_strom", "Strom", "mdi:current-ac", "amber"),
            _kachel("sensor.es_hp_spannung", "Spannung", None, "amber"),
            _kachel("sensor.es_hp_luefter_drehzahl", "Ventilator", None, "indigo"),
            _kachel("sensor.es_hp_mischventil_1", "Mischer 1", None, "teal"),
        ),
        _abschnitt(
            _kopf("Diagnose-Parameter"),
            {
                "type": "markdown", "grid_options": VOLL,
                "content": (
                    "Nicht eindeutig zugeordnete Werte sind standardmäßig "
                    "**deaktiviert**. Aktivieren unter *Einstellungen → Geräte & "
                    "Dienste → ES Heatpump → Entitäten*."
                ),
            },
            {
                "type": "entities", "grid_options": VOLL,
                "entities": [
                    {"entity": "sensor.es_hp_diag_par39", "name": "par39"},
                    {"entity": "sensor.es_hp_diag_par40", "name": "par40"},
                    {"entity": "sensor.es_hp_software_version", "name": "Software Version"},
                    {"entity": "sensor.es_hp_hwtbh_betriebszeit", "name": "HWTBH Betriebszeit"},
                ],
            },
        ),
    ]

    # Auswertung: Die Karte braucht die volle Breite, deshalb spannt ihr
    # Abschnitt alle Spalten.  Darunter Statistik-Diagramme als Rueckfall.
    energie_reihen = [
        {"entity": "sensor.es_hp_energie_elektrisch", "name": "Strom"},
        {"entity": "sensor.es_hp_energie_thermisch", "name": "Wärme"},
    ]
    auswertung = [
        {
            **_abschnitt(
                _kopf("Auswertung"),
                {"type": ANALYSIS_CARD_TYPE, "title": "", "grid_options": VOLL},
            ),
            "column_span": 3,
        },
        _abschnitt(
            _kopf("Energie je Tag"),
            {
                "type": "statistics-graph", "title": "Letzte 30 Tage",
                "entities": energie_reihen, "chart_type": "bar", "period": "day",
                "days_to_show": 30, "stat_types": ["change"], "grid_options": VOLL,
            },
        ),
        _abschnitt(
            _kopf("Energie je Monat"),
            {
                "type": "statistics-graph", "title": "Letzte 12 Monate",
                "entities": energie_reihen, "chart_type": "bar", "period": "month",
                "days_to_show": 365, "stat_types": ["change"], "grid_options": VOLL,
            },
        ),
    ]

    def ansicht(titel: str, pfad: str, icon: str, abschnitte: list) -> dict[str, Any]:
        return {
            "title": titel, "path": pfad, "icon": icon, "type": "sections",
            "max_columns": 3, "theme": ORIGAMI_THEME_NAME, "sections": abschnitte,
        }

    return [
        ansicht("Übersicht", "overview", "mdi:heat-pump", uebersicht),
        ansicht("Energie", "energy", "mdi:lightning-bolt", energie),
        ansicht("Auswertung", "auswertung", "mdi:chart-box-outline", auswertung),
        ansicht("Diagnose", "diagnose", "mdi:bug-outline", diagnose),
    ]


def gestalte(
    config: dict[str, Any], *, design: str, hydraulik: bool,
) -> dict[str, Any]:
    """Gibt eine angepasste Kopie der Dashboard-Konfiguration zurück."""
    cfg = copy.deepcopy(config)
    if design == DESIGN_ORIGAMI:
        cfg["views"] = origami_ansichten(hydraulik)
        return cfg

    views: list[dict[str, Any]] = cfg.get("views") or []

    if hydraulik and views:
        karten = views[0].setdefault("cards", [])
        # Hinter die Kopfzeile (Markdown), falls vorhanden, sonst ganz nach oben.
        pos = 1 if karten and karten[0].get("type") == "markdown" else 0
        karten.insert(pos, hydraulik_karte())

    for view in views:
        view.pop("theme", None)

    return cfg
