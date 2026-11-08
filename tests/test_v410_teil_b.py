"""Tests für Teil B von v4.1.0: Diagnose-Schwärzung, COP-Reparaturhinweis,
Benutzerwechsel im Reconfigure-Dialog und das Ereignis bei Einstellungsänderung.

Nur die reine Logik (diagnose.py, plausibilitaet.py, konto.py, backup.py) –
ohne Home Assistant.

Aufruf:  python3 -m pytest tests/ -q
"""
import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_v410b"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    voll = f"{_PKG}.{name}"
    if voll in sys.modules:
        return sys.modules[voll]
    spec = importlib.util.spec_from_file_location(voll, _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[voll] = modul
    spec.loader.exec_module(modul)
    return modul


C = _lade("const")
_lade("settings")
B = _lade("backup")
D = _lade("diagnose")
P = _lade("plausibilitaet")
K = _lade("konto")
M = _lade("metadata")

X = D.GESCHWAERZT


# ── Diagnose ────────────────────────────────────────────────────────────────

def test_pflichtschluessel_werden_geschwaerzt():
    for k in ("password", "username", "mac", "seriennummer", "seriennummer_innengeraet",
              "seriennummer_aussengeraet", "artikelnummer", "besitzer", "standort",
              "installateur", "installateur_kuerzel", "mn", "devid", "portal_kennung",
              "JSESSIONID", "Cookie", "cookies", "email"):
        assert D.ist_zu_schwaerzen(k), k
    for k in ("modell", "par4", "garantie_bis", "base_url", "inbetriebnahme", "title", 3):
        assert not D.ist_zu_schwaerzen(k), k


def test_stammdaten_felder_gegen_metadata():
    """Jedes personen- oder geraetebezogene Feld der echten Stammdaten wird
    geschwaerzt; die unkritischen bleiben lesbar (Fehlersuche)."""
    voll = M.Stammdaten(**{
        f: f"wert_{f}" for f in M.Stammdaten.__dataclass_fields__ if f != "rohdaten"
    }).als_dict()
    aus = D.schwaerze({"stammdaten": voll})["stammdaten"]
    unkritisch = {
        "modell", "inbetriebnahme", "garantie_bis", "zeitzone",
        "angelegt_am", "zuletzt_geaendert",
    }
    for feld, wert in aus.items():
        if feld in unkritisch:
            assert wert == voll[feld], feld
        else:
            assert wert == X, f"{feld} nicht geschwaerzt"
    # Neue Felder in metadata.py muessen hier bewusst eingeordnet werden
    assert set(voll) - unkritisch == {
        "seriennummer", "seriennummer_innengeraet", "seriennummer_aussengeraet",
        "artikelnummer", "mac", "mn", "devid", "installateur",
        "installateur_kuerzel", "besitzer", "standort",
    }


def test_schwaerzung_verschachtelt():
    daten = {
        "eintrag": {"data": {"username": "max@example.org", "password": "geheim",
                             "base_url": "https://eu.myheatpump.com"}},
        "raw_meta": {"mn": 10309, "devid": 1, "err1": 0, "errs": []},
        "stammdaten": {"modell": "AWC12-R32-M-V8", "seriennummer_aussengeraet": "230101",
                       "besitzer": "Max", "installateur_kuerzel": "XY", "standort": ""},
        "liste": [{"cookies": {"JSESSIONID": "abc"}}],
    }
    aus = D.schwaerze(daten)
    assert aus["eintrag"]["data"]["username"] == X
    assert aus["eintrag"]["data"]["password"] == X
    assert aus["eintrag"]["data"]["base_url"] == "https://eu.myheatpump.com"
    assert aus["raw_meta"] == {"mn": X, "devid": X, "err1": 0, "errs": []}
    assert aus["stammdaten"]["modell"] == "AWC12-R32-M-V8"
    assert aus["stammdaten"]["seriennummer_aussengeraet"] == X
    assert aus["stammdaten"]["besitzer"] == X
    assert aus["stammdaten"]["installateur_kuerzel"] == X
    assert aus["stammdaten"]["standort"] == ""        # leer bleibt sichtbar leer
    assert aus["liste"][0]["cookies"] == X
    # Original unveraendert
    assert daten["eintrag"]["data"]["password"] == "geheim"


def test_zu_schwaerzende_schluessel_sammelt_schreibweisen():
    daten = {"a": {"JSESSIONID": 1, "jsessionid": 2}, "b": [{"MAC": "x"}], "par1": 3}
    assert D.zu_schwaerzende_schluessel(daten) == {"JSESSIONID", "jsessionid", "MAC"}


def test_emails_und_benutzer_in_texten():
    daten = {
        "title": "ES Heatpump (max@example.org)",
        "grund": "Kontakt: Info@Firma-Heizung.de, Konto max",
        "liste": ["es_heatpump_maxmuster_par4"],
        "zahl": 4,
    }
    aus = D.schwaerze_texte(daten, ["maxmuster", None, "ab"])
    assert aus["title"] == f"ES Heatpump ({X})"
    assert "Firma-Heizung" not in aus["grund"] and X in aus["grund"]
    assert aus["grund"].endswith("Konto max")       # zu kurz/kein Treffer
    assert aus["liste"] == [f"es_heatpump_{X}_par4"]
    assert aus["zahl"] == 4


# ── COP-Plausibilitaet ──────────────────────────────────────────────────────

def test_cop_waechter_meldet_erst_nach_folge():
    w = P.CopWaechter(5)
    for _ in range(4):
        assert w.messpunkt(0.6) is None
    assert w.messpunkt(0.6) == P.AKTION_MELDEN
    assert w.messpunkt(0.6) is None                # nur einmal melden
    assert w.messpunkt(3.2) == P.AKTION_LOESCHEN
    assert w.messpunkt(3.2) is None


def test_cop_waechter_einzelne_ausreisser():
    w = P.CopWaechter(5)
    for cop in (0.5, 0.7, 0.9, 0.8, 1.5, 0.5, 0.5, 0.5, 0.5):
        assert w.messpunkt(cop) is None
    assert w.serie == 4


def test_cop_waechter_stillstand_unterbricht_nicht():
    w = P.CopWaechter(3)
    assert w.messpunkt(0.5) is None
    assert w.messpunkt(0.0) is None
    assert w.messpunkt(None) is None
    assert w.messpunkt(0.5) is None
    assert w.messpunkt(0.5) == P.AKTION_MELDEN
    # Stillstand loescht den Hinweis nicht
    assert w.messpunkt(0.0) is None and w.gemeldet


def test_cop_konstanten():
    assert P.COP_UNPLAUSIBEL_FOLGE == 5
    assert P.ISSUE_COP_UNPLAUSIBEL == "cop_unplausibel"
    assert P.cop_issue_id("abc") == "cop_unplausibel_abc"
    # v4.1.1: eigener Text fuer den Warmwasserbetrieb, gleiche Issue-ID
    assert P.ISSUE_COP_UNPLAUSIBEL_WW == "cop_unplausibel_warmwasser"
    assert P.cop_issue_schluessel("Brauchwasser") == "cop_unplausibel_warmwasser"
    for modus in ("Heizen", "Brauchwasser + Heizen", "Unbekannt", None):
        assert P.cop_issue_schluessel(modus) == "cop_unplausibel", modus
    assert P.COP_LEARN_MORE_URL.endswith("#-den-volumenstrom-richtig-einstellen")
    readme = (_ROOT.parents[1] / "README.md").read_text(encoding="utf-8")
    assert "#### ⚠️ Den Volumenstrom richtig einstellen" in readme


def test_richtwert_text():
    assert P.richtwert_text("AWC12-R32-M-V8") == "AWC12-R32-M-V8: 2.02 m³/h"
    alle = P.richtwert_text(C.MODEL_UNKNOWN)
    assert "AWC6 1.01" in alle and "AWC19 3.28" in alle and alle.endswith("m³/h")
    assert P.richtwert_text(None) == alle


# ── Benutzerwechsel ─────────────────────────────────────────────────────────

def test_umbenannte_unique_id():
    f = K.umbenannte_unique_id
    assert f("es_heatpump_alt_par4", "es_heatpump", "alt", "neu") == "es_heatpump_neu_par4"
    assert f("es_heatpump_alt_cfg_par1", "es_heatpump", "alt", "neu") == "es_heatpump_neu_cfg_par1"
    # Benutzername kommt im Rest vor: nur das Praefix ersetzen
    assert f("es_heatpump_alt_calc_alt_x", "es_heatpump", "alt", "neu") == "es_heatpump_neu_calc_alt_x"
    assert f("anderes_alt_par4", "es_heatpump", "alt", "neu") is None
    assert f("es_heatpump_alt_par4", "es_heatpump", "alt", "alt") is None
    assert f(None, "es_heatpump", "alt", "neu") is None


def test_neuer_titel():
    assert K.neuer_titel("ES Heatpump (alt)", "alt", "neu") == "ES Heatpump (neu)"
    assert K.neuer_titel("Keller", "alt", "neu") == "Keller"


# ── Ereignis bei Einstellungsaenderung ──────────────────────────────────────

def test_ereignis_nicht_ohne_vorherigen_stand():
    assert B.aenderungen_fuer_ereignis(None, {"par1": 1}) == []
    assert B.aenderungen_fuer_ereignis({}, {"par1": 1}) == []
    assert B.aenderungen_fuer_ereignis({"par1": 1}, {"par1": 1.0}) == []


def test_ereignis_nutzlast():
    S = sys.modules[f"{_PKG}.settings"]
    bekannt = next(p for p, s in S.SETTINGS.items() if s.kind == S.KIND_NUMBER and s.unit)
    alt = {bekannt: 38.0, "par299": 0.0}
    neu = {bekannt: 40.0, "par299": 5.0}
    aenderungen = B.aenderungen_fuer_ereignis(alt, neu)
    assert [a["par"] for a in aenderungen] == [bekannt, "par299"]
    erste = aenderungen[0]
    assert set(erste) == {"par", "name", "gruppe", "alt", "neu", "text"}
    assert erste["alt"] == 38 and erste["neu"] == 40
    assert erste["text"].startswith(f"{S.SETTINGS[bekannt].name}: 38")
    assert "→" in erste["text"]
    assert aenderungen[1]["text"] == "Unbenanntes Feld par299: 0 → 5"


def test_ereignis_text_kuerzt_und_sortiert():
    aenderungen = [
        {"text": "u1", "gruppe": "Ohne Katalogeintrag"},
        {"text": "a", "gruppe": "Heizen"},
        {"text": "b", "gruppe": "Heizen"},
        {"text": "c", "gruppe": "Warmwasser"},
        {"text": "d", "gruppe": "Warmwasser"},
    ]
    assert B.ereignis_text(aenderungen) == "a; b; c (+2)"
    assert B.ereignis_text(aenderungen[:2]) == "a; u1"
    assert B.ereignis_text([]) == ""


def test_ereignisname():
    assert C.EVENT_EINSTELLUNG_GEAENDERT == "es_heatpump_einstellung_geaendert"
