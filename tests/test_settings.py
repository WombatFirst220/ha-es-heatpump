"""Tests für den Katalog der schreibbaren Parameter (v3.0.0).

Der Katalog ist die letzte Stelle, an der ein falscher Wert aufzuhalten ist,
bevor er in einer Heizung landet. Entsprechend genau wird er geprüft.

Aufruf:  python3 -m pytest tests/ -q
   oder:  python3 tests/test_settings.py
"""
import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test"
if _PKG not in sys.modules:
    _paket = types.ModuleType(_PKG)
    _paket.__path__ = [str(_ROOT)]
    sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


S = _lade("settings")


def test_katalog_ist_vollstaendig():
    """74 Felder in 14 Gruppen, aus dem Portal abgelesen."""
    assert len(S.SETTINGS) == 74
    assert len(S.GROUPS) == 14
    # Jeder Eintrag hat einen deutschen Namen, keine Portal-Rohbeschriftung
    for par, s in S.SETTINGS.items():
        assert s.par == par
        assert s.name and not s.name.startswith("par")
        assert s.group in S.GROUPS
        assert s.kind in (S.KIND_NUMBER, S.KIND_SELECT, S.KIND_SWITCH, S.KIND_READONLY)


def test_slugs_sind_eindeutig_und_haben_cfg_praefix():
    """Ohne cfg-Präfix kollidierten Einstellungen mit Messwerten.

    Das Portal führt parXX zweimal: par1 ist in den Messwerten die Betriebsart
    und in den Einstellungen "Anlage ein/aus". Genau dieser Fehler wäre teuer.
    """
    slugs = [s.slug for s in S.SETTINGS.values()]
    assert len(slugs) == len(set(slugs))
    assert all(s.startswith("cfg_") for s in slugs)


def test_zahlenwerte_haben_grenzen():
    for s in S.SETTINGS.values():
        if s.kind == S.KIND_NUMBER:
            assert s.minimum is not None and s.maximum is not None, s.par
            assert s.minimum <= s.maximum, s.par


def test_auswahlen_haben_optionen():
    for s in S.SETTINGS.values():
        if s.kind == S.KIND_SELECT:
            assert len(s.options) >= 2, s.par
            assert all(isinstance(k, int) for k in s.options)


def test_grenzen_werden_durchgesetzt():
    """Der Kern: Ein Wert außerhalb des Bereichs darf das Gerät nie erreichen."""
    warmwasser = S.SETTINGS["par55"]            # Setpoint DHW, 25..75 °C
    assert warmwasser.validate(50) == 50
    assert warmwasser.validate(25) == 25
    assert warmwasser.validate(75) == 75
    for schlecht in (24, 76, 200, -5):
        try:
            warmwasser.validate(schlecht)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{schlecht} hätte abgelehnt werden müssen")


def test_auswahl_wird_durchgesetzt():
    betriebsart = S.SETTINGS["par4"]            # 0..4
    assert betriebsart.validate(0) == 0
    assert betriebsart.validate(4) == 4
    for schlecht in (5, -1, 99):
        try:
            betriebsart.validate(schlecht)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{schlecht} hätte abgelehnt werden müssen")


def test_schalter_nimmt_nur_null_und_eins():
    schalter = S.SETTINGS["par41"]              # Legionellenschutz
    assert schalter.kind == S.KIND_SWITCH
    assert schalter.validate(0) == 0
    assert schalter.validate(1) == 1
    try:
        schalter.validate(2)
    except ValueError:
        pass
    else:
        raise AssertionError("2 hätte abgelehnt werden müssen")


def test_nur_lesbare_felder_sind_gesperrt():
    """Firmware-Versionsnummern stehen im Formular, sind aber keine Einstellung."""
    for par in ("par2", "par3", "par137", "par138"):
        s = S.SETTINGS[par]
        assert s.kind == S.KIND_READONLY
        assert not s.writable
        try:
            s.validate(1)
        except ValueError as err:
            assert "nicht schreibbar" in str(err)
        else:
            raise AssertionError(f"{par} hätte gesperrt sein müssen")
    assert len(S.WRITABLE) == 70


def test_kommazahlen_werden_gerundet():
    """Das Gerät nimmt nur ganze Zahlen; 49.6 darf nicht als 49 durchrutschen."""
    assert S.SETTINGS["par55"].validate(49.6) == 50
    assert S.SETTINGS["par55"].validate(49.4) == 49


def test_text_statt_zahl_wird_abgelehnt():
    try:
        S.SETTINGS["par55"].validate("warm")
    except ValueError:
        pass
    else:
        raise AssertionError("Text hätte abgelehnt werden müssen")


def test_klartextfassung():
    assert S.beschreibe("par1", 1) == "Anlage ein/aus: Ein"
    assert S.beschreibe("par1", 0) == "Anlage ein/aus: Aus"
    assert S.beschreibe("par4", 2) == "Betriebsart: Kühlen"
    assert S.beschreibe("par55", 50) == "Warmwasser Solltemperatur: 50 °C"
    # Unbekanntes Feld bleibt lesbar statt zu scheitern
    assert S.beschreibe("par999", 7) == "par999 = 7"


if __name__ == "__main__":
    fehler = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as err:
                fehler += 1
                print(f"  FEHL {name}: {err}")
    print(f"\n{'alle Prüfungen bestanden' if not fehler else f'{fehler} Fehler'}")
    sys.exit(1 if fehler else 0)
