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
    assert set(_layout.MODE_MAP) == set(_const.BETRIEBSART_OPTIONS)
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
