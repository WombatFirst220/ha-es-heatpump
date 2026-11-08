"""Tests für die nativen Übersetzungen (GitHub-Issue #6).

Prüft ohne Home Assistant, dass jeder translation_key, den der Code vergibt,
in strings.json, translations/en.json und translations/de.json einen Namen hat
- samt Zuständen der Betriebsart und der Auswahllisten, Fehlermeldungen und
Diensten. da/nl/sv müssen dieselben Schlüssel wie strings.json haben.

Aufruf:  python3 -m pytest tests/ -q
"""
import importlib.util
import json
import pathlib
import re
import string
import sys
import types

import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_uebersetzung"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


C = _lade("const")
S = _lade("settings")
_lade("flow")
E = _lade("energy")
_layout = _lade("dashboard_layout")

_PFLICHT = {
    "strings": _ROOT / "strings.json",
    "en": _ROOT / "translations" / "en.json",
    "de": _ROOT / "translations" / "de.json",
}
_SCHLUESSEL = re.compile(r"^[a-z0-9_]+$")
_WEITERE = ("da", "nl", "sv")


def _json(pfad):
    with pfad.open(encoding="utf-8") as fh:
        return json.load(fh)


def _alle():
    return {k: _json(p) for k, p in _PFLICHT.items()}


def _kind_plattform(s):
    return {S.KIND_NUMBER: "number", S.KIND_SELECT: "select", S.KIND_SWITCH: "switch"}[s.kind]


def _code_schluessel():
    """translation_keys, die im Code stehen: (plattform, key)."""
    erwartet = set()
    for meta in C.PARAMETER_SENSORS.values():
        erwartet.add(("sensor", meta["slug"]))
    for s in S.SETTINGS.values():
        if s.writable:
            erwartet.add((_kind_plattform(s), s.slug))
    # Zaehler der Auswertungsseite (translation_key = slug)
    for slug, _, _ in E.ENERGIE_ZAEHLER:
        erwartet.add(("sensor", slug))
    # Feste _attr_translation_key = "..." aus den Plattform-Dateien
    for plattform in ("sensor", "button", "number", "select", "switch"):
        quelle = (_ROOT / f"{plattform}.py").read_text(encoding="utf-8")
        for key in re.findall(r'_attr_translation_key\s*=\s*"([^"]+)"', quelle):
            erwartet.add((plattform, key))
    return erwartet


def test_alle_json_dateien_sind_gueltig():
    for pfad in list(_PFLICHT.values()) + sorted((_ROOT / "translations").glob("*.json")):
        _json(pfad)


def _flach(daten, praefix=""):
    """Verschachteltes JSON -> {"a.b.c": wert}."""
    aus = {}
    for k, v in daten.items():
        if isinstance(v, dict):
            aus.update(_flach(v, f"{praefix}{k}."))
        else:
            aus[f"{praefix}{k}"] = v
    return aus


def _platzhalter(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_weitere_sprachen_vollstaendig():
    """da/nl/sv haben genau die Schluessel von strings.json, keiner ist leer."""
    vorlage = _flach(_json(_PFLICHT["strings"]))
    for sprache in _WEITERE:
        daten = _flach(_json(_ROOT / "translations" / f"{sprache}.json"))
        assert set(daten) - set(vorlage) == set(), (sprache, "verwaist")
        assert set(vorlage) - set(daten) == set(), (sprache, "fehlend")
        leer = sorted(k for k, v in daten.items() if not isinstance(v, str) or not v.strip())
        assert not leer, (sprache, leer)


def test_weitere_sprachen_platzhalter():
    """Platzhalter wie {name} oder {theme} bleiben in allen Sprachen gleich."""
    vorlage = _flach(_json(_PFLICHT["strings"]))
    for sprache in _WEITERE:
        daten = _flach(_json(_ROOT / "translations" / f"{sprache}.json"))
        for k, v in vorlage.items():
            assert _platzhalter(daten[k]) == _platzhalter(v), (sprache, k)


def test_strings_json_gleich_en_json():
    assert _json(_PFLICHT["strings"]) == _json(_PFLICHT["en"])


def test_feste_translation_keys_werden_gefunden():
    """Sicherung gegen einen Regex, der still nichts mehr findet."""
    keys = {k for _, k in _code_schluessel()}
    for k in ("spreizung", "thermische_leistung", "aktueller_cop", "leistung_elektrisch",
              "betriebsart", "anlagendaten", "konfigurationssicherungen",
              "konfiguration_sichern", "energie_elektrisch", "energie_thermisch_warmwasser",
              "verdichter_starts", "verdichter_laufzeit"):
        assert k in keys, k


def test_jeder_translation_key_hat_einen_namen():
    erwartet = _code_schluessel()
    for sprache, daten in _alle().items():
        entity = daten.get("entity", {})
        fehlend = sorted(
            f"{p}.{k}" for p, k in erwartet
            if not entity.get(p, {}).get(k, {}).get("name")
        )
        assert not fehlend, (sprache, fehlend)


def test_keine_verwaisten_uebersetzungen():
    erwartet = _code_schluessel()
    for sprache, daten in _alle().items():
        vorhanden = {(p, k) for p, d in daten["entity"].items() for k in d}
        assert vorhanden <= erwartet, (sprache, vorhanden - erwartet)


def test_translation_keys_sind_gueltig():
    for _, key in _code_schluessel():
        assert _SCHLUESSEL.match(key), key


def test_deutsche_sensornamen_entsprechen_const():
    de = _json(_PFLICHT["de"])["entity"]["sensor"]
    for meta in C.PARAMETER_SENSORS.values():
        assert de[meta["slug"]]["name"] == meta["name"], meta["slug"]


def test_deutsche_einstellungsnamen_entsprechen_settings():
    de = _json(_PFLICHT["de"])["entity"]
    for s in S.SETTINGS.values():
        if s.writable:
            assert de[_kind_plattform(s)][s.slug]["name"] == f"{s.group}: {s.name}"


def test_betriebsart_zustaende():
    assert list(C.BETRIEBSART_STATE_KEYS) == C.BETRIEBSART_OPTIONS
    # "Unbekannt" bildet bewusst auf None ab (HA-Zustand unknown), nicht auf
    # einen eigenen Schluessel "unknown", der davon nicht zu unterscheiden waere.
    assert C.BETRIEBSART_STATE_KEYS["Unbekannt"] is None
    werte = [w for w in C.BETRIEBSART_STATE_KEYS.values() if w is not None]
    assert len(set(werte)) == len(werte)
    assert C.BETRIEBSART_STATE_OPTIONS == werte
    assert all(_SCHLUESSEL.match(w) for w in werte)
    for sprache, daten in _alle().items():
        zustand = daten["entity"]["sensor"]["betriebsart"].get("state", {})
        assert set(zustand) == set(werte), sprache
        assert all(zustand.values()), sprache


def test_mode_map_der_hydraulikkarte_nutzt_zustands_schluessel():
    # "unknown" ist HAs eigener Zustand, wenn die Betriebsart nicht bestimmbar ist.
    assert set(_layout.MODE_MAP) == set(C.BETRIEBSART_STATE_OPTIONS) | {"unknown"}


def test_auswahllisten_zustaende():
    for s in S.SETTINGS.values():
        if s.kind != S.KIND_SELECT:
            continue
        for sprache, daten in _alle().items():
            zustand = daten["entity"]["select"][s.slug].get("state", {})
            assert set(zustand) == set(s.option_keys.values()), (sprache, s.par)
            assert all(zustand.values()), (sprache, s.par)


def test_fehlermeldungen():
    # Schluessel aus translation_key="..." in den Plattform-Dateien
    keys = set()
    for pfad in _ROOT.glob("*.py"):
        keys |= set(re.findall(r'translation_key="([^"]+)"', pfad.read_text(encoding="utf-8")))
    assert {"schreibzugriff_aus", "konfiguration_unbekannt"} <= keys
    en_platzhalter = None
    for sprache, daten in _alle().items():
        exc = daten.get("exceptions", {})
        for k in keys:
            assert exc.get(k, {}).get("message"), (sprache, k)
        platzhalter = {
            k: {f for _, f, _, _ in string.Formatter().parse(exc[k]["message"]) if f}
            for k in keys
        }
        if en_platzhalter is None:
            en_platzhalter = platzhalter
        assert platzhalter == en_platzhalter, sprache
    assert en_platzhalter["schreibzugriff_aus"] == {"name"}


def test_dienste_vollstaendig_uebersetzt():
    with (_ROOT / "services.yaml").open(encoding="utf-8") as fh:
        dienste = yaml.safe_load(fh)
    for sprache, daten in _alle().items():
        uebersetzt = daten.get("services", {})
        assert set(uebersetzt) == set(dienste), sprache
        for name, d in dienste.items():
            assert uebersetzt[name]["name"] and uebersetzt[name]["description"]
            felder = set((d.get("fields") or {}))
            assert set(uebersetzt[name].get("fields", {})) == felder, (sprache, name)
            for f in felder:
                assert uebersetzt[name]["fields"][f]["name"], (sprache, name, f)
