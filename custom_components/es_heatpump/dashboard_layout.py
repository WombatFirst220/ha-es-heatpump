"""
dashboard_layout.py
───────────────────
Passt die mitgelieferte Dashboard-Konfiguration an die Optionen an (v3.1.0):

  * **Hydraulik-Schema** – setzt die Heat Pump Hydraulic Card
    (Sturmi77/heatpump-hydraulic-card, MIT, mitgeliefert unter ``www/``) als
    erste Karte in die Übersicht.
  * **Design** – ``origami`` setzt das Theme „Origami“ als View-Theme auf
    jede Ansicht dieses Dashboards. Andere Dashboards und das Benutzer-Theme
    bleiben unberührt.

Ohne Home-Assistant-Abhängigkeit, damit es sich ohne HA testen lässt.
"""
from __future__ import annotations

import copy
from typing import Any

from .const import DESIGN_ORIGAMI, ORIGAMI_THEME_NAME

HYDRAULIC_CARD_TYPE = "custom:heatpump-hydraulic-card"

# Betriebsart der Integration → Modus der Karte.  Die Karte kennt off, heating,
# dhw, cooling, defrost, idle.  Kombinierte Zustände zeigen Warmwasser, weil das
# Umschaltventil dann zum Speicher steht.
MODE_MAP: dict[str, str] = {
    "Aus": "off",
    "Heizen": "heating",
    "Brauchwasser": "dhw",
    "Brauchwasser + Heizen": "dhw",
    "Kuehlen": "cooling",
    "Brauchwasser + Kuehlen": "dhw",
    "Entfrosten": "defrost",
    "Unbekannt": "idle",
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


def gestalte(
    config: dict[str, Any], *, design: str, hydraulik: bool,
) -> dict[str, Any]:
    """Gibt eine angepasste Kopie der Dashboard-Konfiguration zurück."""
    cfg = copy.deepcopy(config)
    views: list[dict[str, Any]] = cfg.get("views") or []

    if hydraulik and views:
        karten = views[0].setdefault("cards", [])
        # Hinter die Kopfzeile (Markdown), falls vorhanden, sonst ganz nach oben.
        pos = 1 if karten and karten[0].get("type") == "markdown" else 0
        karten.insert(pos, hydraulik_karte())

    for view in views:
        if design == DESIGN_ORIGAMI:
            view["theme"] = ORIGAMI_THEME_NAME
        else:
            view.pop("theme", None)

    return cfg
