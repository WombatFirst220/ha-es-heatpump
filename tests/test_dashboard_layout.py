"""Tests für die Dashboard-Anpassung (v3.1.0): Hydraulik-Karte und Origami.

Ohne Home-Assistant-Abhängigkeit, siehe Kopf von tests/test_mode.py.
"""
import importlib.util
import json
import pathlib
import sys
import types

import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_layout"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


_const = _lade("const")
_layout = _lade("dashboard_layout")


def _bundled():
    with (_ROOT / "dashboard" / "es_heatpump.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _karten(cfg):
    return [c for v in cfg["views"] for c in v.get("cards", [])]


def test_standard_ohne_karte_entspricht_dem_original():
    original = _bundled()
    cfg = _layout.gestalte(original, design="standard", hydraulik=False)
    assert cfg == original
    assert cfg is not original


def test_hydraulik_karte_steht_hinter_der_kopfzeile():
    cfg = _layout.gestalte(_bundled(), design="standard", hydraulik=True)
    karten = cfg["views"][0]["cards"]
    assert karten[0]["type"] == "markdown"
    assert karten[1]["type"] == _layout.HYDRAULIC_CARD_TYPE
    assert sum(k["type"] == _layout.HYDRAULIC_CARD_TYPE for k in _karten(cfg)) == 1


def test_origami_setzt_theme_auf_jede_ansicht():
    cfg = _layout.gestalte(_bundled(), design="origami", hydraulik=False)
    assert all(v["theme"] == _const.ORIGAMI_THEME_NAME for v in cfg["views"])
    zurueck = _layout.gestalte(_bundled(), design="standard", hydraulik=False)
    assert all("theme" not in v for v in zurueck["views"])


# Berechnete Zaehler fuer die Auswertung (v4.0.0, sensor.py)
_ENERGIE_SENSOREN = {f"sensor.es_hp_{x}" for x in (
    "energie_elektrisch", "energie_elektrisch_heizen", "energie_elektrisch_warmwasser",
    "energie_thermisch", "energie_thermisch_heizen", "energie_thermisch_warmwasser",
    "verdichter_starts", "verdichter_laufzeit")}


# Neue Entities v4.1.0 (binary_sensor.py, sensor.py)
_NEU_V410 = {
    "binary_sensor.es_hp_verdichter", "binary_sensor.es_hp_abtauen",
    "binary_sensor.es_hp_warmwasserbereitung", "binary_sensor.es_hp_takten",
    "sensor.es_hp_carnot_guetegrad", "sensor.es_hp_energie_elektrisch_standby",
}


def _ids(karten):
    """Alle Entity-IDs in Karten (auch verschachtelt, Badges, Listen)."""
    ids = set()
    for k in karten:
        if "entity" in k:
            ids.add(k["entity"])
        for b in k.get("badges", []):
            ids.add(b["entity"] if isinstance(b, dict) else b)
        if isinstance(k.get("entities"), list):
            for e in k["entities"]:
                ids.add(e if isinstance(e, str) else e["entity"])
        ids |= _ids(k.get("cards", []))
    return ids


def _origami_karten(cfg):
    return [c for v in cfg["views"] for s in v["sections"] for c in s["cards"]]


def test_origami_ist_abschnitts_ansicht_mit_gleichen_pfaden():
    standard = _bundled()
    cfg = _layout.gestalte(standard, design="origami", hydraulik=True)
    assert [v["path"] for v in cfg["views"]] == [v["path"] for v in standard["views"]]
    for v in cfg["views"]:
        assert v["type"] == "sections"
        for s in v["sections"]:
            assert s["cards"][0]["type"] == "heading"


def test_origami_hydraulik_nur_wenn_gewuenscht():
    mit = _origami_karten(_layout.gestalte(_bundled(), design="origami", hydraulik=True))
    ohne = _origami_karten(_layout.gestalte(_bundled(), design="origami", hydraulik=False))
    assert sum(k["type"] == _layout.HYDRAULIC_CARD_TYPE for k in mit) == 1
    assert not any(k["type"] == _layout.HYDRAULIC_CARD_TYPE for k in ohne)


def test_origami_nutzt_nur_bekannte_entities():
    bekannt = {f"sensor.es_hp_{p['slug']}" for p in _const.PARAMETER_SENSORS.values()}
    bekannt |= {f"sensor.es_hp_{x}" for x in (
        "betriebsart", "leistung_elektrisch", "thermische_leistung",
        "aktueller_cop", "spreizung")}
    bekannt.add("number.es_hp_cfg_par55")
    bekannt |= _ENERGIE_SENSOREN
    bekannt |= _NEU_V410
    ids = set()
    for k in _origami_karten(_layout.gestalte(_bundled(), design="origami", hydraulik=True)):
        if "entity" in k:
            ids.add(k["entity"])
        for b in k.get("badges", []):
            ids.add(b["entity"])
        for e in k.get("entities", []) if isinstance(k.get("entities"), list) else []:
            ids.add(e if isinstance(e, str) else e["entity"])
    assert ids and ids <= bekannt, ids - bekannt


def test_mode_map_deckt_alle_betriebsarten_ab():
    # "unknown" = HAs eigener Zustand, wenn die Betriebsart nicht bestimmbar ist
    # dazu die deutschen Zustaende bis v3.x, die noch in der Historie stehen
    alt = set(_const.BETRIEBSART_STATE_KEYS)
    assert set(_layout.ALTE_BETRIEBSARTEN) == alt
    assert set(_layout.MODE_MAP) == set(_const.BETRIEBSART_STATE_OPTIONS) | {"unknown"} | alt
    # Alter und neuer Zustand landen im selben Modus der Karte
    for alt_wert, neu in _const.BETRIEBSART_STATE_KEYS.items():
        assert _layout.MODE_MAP[alt_wert] == _layout.MODE_MAP[neu or "unknown"], alt_wert
    erlaubt = {"off", "heating", "dhw", "cooling", "defrost", "idle"}
    assert set(_layout.MODE_MAP.values()) <= erlaubt


def test_karte_nutzt_nur_entities_der_integration():
    karte = _layout.hydraulik_karte()
    ids = list(karte["entities"].values()) + [d["entity"] for d in karte["details"]]
    assert all(".es_hp_" in e for e in ids)
    # Sensor-Slugs gegen die Parametertabelle bzw. die berechneten Sensoren
    bekannt = {f"sensor.es_hp_{p['slug']}" for p in _const.PARAMETER_SENSORS.values()}
    bekannt |= {
        "sensor.es_hp_betriebsart", "sensor.es_hp_leistung_elektrisch",
        "sensor.es_hp_thermische_leistung", "number.es_hp_cfg_par55",
    }
    assert set(ids) <= bekannt, set(ids) - bekannt


def test_keine_bedienelemente_auf_dem_schema():
    assert "controls" not in _layout.hydraulik_karte()


def test_uebersetzungen_vollstaendig():
    for datei in ["strings.json", *sorted((_ROOT / "translations").glob("*.json"))]:
        pfad = _ROOT / datei if isinstance(datei, str) else datei
        d = json.loads(pfad.read_text(encoding="utf-8"))
        felder = d["options"]["step"]["init"]["data"]
        assert {"hydraulic_card", "dashboard_design"} <= set(felder), pfad.name
        assert set(d["selector"]["dashboard_design"]["options"]) == set(_const.DESIGN_OPTIONS)
        assert "{theme}" in d["issues"]["origami_theme_missing"]["description"]


def test_einstellungsabschnitte_vollstaendig_und_eindeutig():
    """Jedes Optionsfeld steht in jeder Sprache in genau einem Abschnitt (v3.1.1)."""
    import re
    quelle = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    abschnitte = re.findall(r'^SEC_\w+\s*=\s*"(\w+)"', quelle, re.M)
    assert abschnitte == ["messung", "dashboard", "zugriff", "verbindung"]
    for pfad in [_ROOT / "strings.json", *sorted((_ROOT / "translations").glob("*.json"))]:
        init = json.loads(pfad.read_text(encoding="utf-8"))["options"]["step"]["init"]
        sek = init["sections"]
        assert list(sek) == abschnitte, pfad.name
        gesehen = [k for s in sek.values() for k in s["data"]]
        assert len(gesehen) == len(set(gesehen)), pfad.name
        assert set(gesehen) == set(init["data"]), pfad.name
        for s in sek.values():
            assert s["name"]
            assert set(s.get("data_description", {})) <= set(s["data"])


def _ansicht(cfg, pfad):
    treffer = [v for v in cfg["views"] if v.get("path") == pfad]
    assert len(treffer) == 1, pfad
    return treffer[0]


def _alle_karten(karten):
    for k in karten:
        yield k
        yield from _alle_karten(k.get("cards", []))


def test_auswertung_im_standard_dashboard():
    for hydraulik in (False, True):
        cfg = _layout.gestalte(_bundled(), design="standard", hydraulik=hydraulik)
        view = _ansicht(cfg, "auswertung")
        assert view["icon"] == "mdi:chart-box-outline"
        karten = list(_alle_karten(view["cards"]))
        assert sum(k["type"] == _layout.ANALYSIS_CARD_TYPE for k in karten) == 1
        # Keine statistics-graph-Rueckfallkarten mehr (v4.0.1)
        assert not [k for k in karten if k["type"] == "statistics-graph"]


def test_auswertung_im_origami_dashboard():
    for hydraulik in (False, True):
        cfg = _layout.gestalte(_bundled(), design="origami", hydraulik=hydraulik)
        view = _ansicht(cfg, "auswertung")
        assert view["icon"] == "mdi:chart-box-outline"
        karten = [c for s in view["sections"] for c in s["cards"]]
        assert sum(k["type"] == _layout.ANALYSIS_CARD_TYPE for k in karten) == 1
        # Der Abschnitt der Karte spannt die ganze Breite
        abschnitt = next(s for s in view["sections"]
                         if any(c["type"] == _layout.ANALYSIS_CARD_TYPE for c in s["cards"]))
        assert abschnitt["column_span"] == view["max_columns"]
        assert not [k for k in karten if k["type"] == "statistics-graph"]


def test_repo_kopie_des_dashboards_hat_gleiche_ansichten():
    with (_ROOT.parents[1] / "dashboards" / "es_heatpump.yaml").open(encoding="utf-8") as fh:
        kopie = yaml.safe_load(fh)
    assert [v["path"] for v in kopie["views"]] == [v["path"] for v in _bundled()["views"]]
    assert _ansicht(kopie, "auswertung") == _ansicht(_bundled(), "auswertung")


def test_auswertungskarte_wird_mitgeliefert():
    quelle = (_ROOT / "www" / "es-heatpump-analysis-card.js").read_text(encoding="utf-8")
    assert 'customElements.define("es-heatpump-analysis-card"' in quelle
    assert "recorder/statistics_during_period" in quelle
    assert "es_heatpump/settings_changes" in quelle
    for slug in _ENERGIE_SENSOREN:
        assert f'"{slug}"' in quelle, slug
    # v4.0.1: Quellen per analysis_config, Rueckfall auf die Leistungsmittel
    assert "es_heatpump/analysis_config" in quelle
    for eid in ("sensor.es_hp_leistung_elektrisch", "sensor.es_hp_thermische_leistung"):
        assert f'"{eid}"' in quelle, eid
    ws = (_ROOT / "websocket_api.py").read_text(encoding="utf-8")
    assert 'f"{DOMAIN}/analysis_config"' in ws
    assert "async_register_command(hass, ws_analysis_config)" in ws
    # v4.1.0: Verlaufsreihen fuer die Zyklen-Rekonstruktion (Takt-Abschnitt)
    assert '"frequency": ("par20", "frequenz_hz")' in ws
    assert '"mode": (CALC_BETRIEBSART, "betriebsart")' in ws
    assert "history/history_during_period" in quelle
    for eid in ("sensor.es_hp_frequenz_hz", "sensor.es_hp_betriebsart"):
        assert f'"{eid}"' in quelle, eid
    assert 'frequency: "frequency", mode: "mode"' in quelle
    # Standard-IDs der Karte passen zu den Slugs der Integration
    assert _const.PARAMETER_SENSORS["par20"]["slug"] == "frequenz_hz"
    assert _const.CALC_BETRIEBSART == "calc_betriebsart"


def test_stromzaehler_option_in_formularen():
    """energy_entity steht im Options-Abschnitt "messung" und ist leerbar (v4.0.1)."""
    quelle = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "entity(CONF_ENERGY_ENTITY, device_class=\"energy\")" in quelle
    assert "CONF_ENERGY_ENTITY, CONF_MODE_SOURCE" in quelle      # _ENTITY_KEYS
    for pfad in [_ROOT / "strings.json", *sorted((_ROOT / "translations").glob("*.json"))]:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        assert d["config"]["step"]["user"]["data"]["energy_entity"], pfad.name
        sek = d["options"]["step"]["init"]["sections"]["messung"]
        assert sek["data"]["energy_entity"] and sek["data_description"]["energy_entity"], pfad.name


def test_neue_entities_v410_in_beiden_designs():
    """Binaersensoren, Carnot und Standby stehen in Energie bzw. Diagnose."""
    standard = _bundled()
    for pfad, erwartet in (
        ("energy", {"sensor.es_hp_carnot_guetegrad", "sensor.es_hp_energie_elektrisch_standby"}),
        ("diagnose", {"binary_sensor.es_hp_verdichter", "binary_sensor.es_hp_abtauen",
                      "binary_sensor.es_hp_warmwasserbereitung", "binary_sensor.es_hp_takten"}),
    ):
        assert erwartet <= _ids(_ansicht(standard, pfad)["cards"]), pfad
        for hydraulik in (False, True):
            cfg = _layout.gestalte(standard, design="origami", hydraulik=hydraulik)
            karten = [c for s in _ansicht(cfg, pfad)["sections"] for c in s["cards"]]
            assert erwartet <= _ids(karten), (pfad, hydraulik)
    # Uebersicht bleibt unveraendert schlank
    assert not (_ids(_ansicht(standard, "overview")["cards"]) & _NEU_V410)


def test_standard_dashboard_neue_ids_sind_bekannt():
    """Beide YAML-Kopien: jede binary_sensor- und v4.1.0-ID gibt es wirklich."""
    for pfad in (_ROOT / "dashboard" / "es_heatpump.yaml",
                 _ROOT.parents[1] / "dashboards" / "es_heatpump.yaml"):
        with pfad.open(encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        ids = _ids([k for v in cfg["views"] for k in v.get("cards", [])])
        binaer = {e for e in ids if e.startswith("binary_sensor.")}
        assert binaer and binaer <= _NEU_V410, (pfad, binaer - _NEU_V410)
        assert _NEU_V410 <= ids, (pfad, _NEU_V410 - ids)
