"""Tests fuer die Energiezaehler der Auswertungsseite und den Aenderungsverlauf.

Bewusst ohne Home Assistant: ``energy.py`` importiert nur aus ``const`` und
``flow``, ``backup.py`` nur aus ``settings`` - alles reines Python.

Aufruf:  python3 -m pytest tests/ -q
"""
import importlib.util
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_energie"
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


_lade("const")
_lade("flow")
E = _lade("energy")
S = _lade("settings")
B = _lade("backup")

H = 3600.0


# ── Hilfsfunktionen ──────────────────────────────────────────────────────

@pytest.mark.parametrize("modus, teil", [
    ("Heizen", E.HEIZEN),
    ("Entfrosten", E.HEIZEN),
    ("Brauchwasser", E.WARMWASSER),
    ("Brauchwasser + Heizen", E.WARMWASSER),
    ("Brauchwasser + Kuehlen", E.WARMWASSER),
    ("Aus", None),
    ("Kuehlen", None),
    ("Unbekannt", None),
    (None, None),
])
def test_kategorie(modus, teil):
    assert E.kategorie_von(modus) == teil


@pytest.mark.parametrize("roh, einheit, erwartet", [
    ("1500", "W", 1500.0),
    ("-1500", "W", 1500.0),        # Bezug negativ gemeldet
    ("1.5", "kW", 1500.0),
    ("200", None, 200.0),
    ("unknown", "W", None),
    ("unavailable", "W", None),
    ("", "W", None),
    ("abc", "W", None),
    ("nan", "W", None),
    ("inf", "W", None),
])
def test_leistung_in_w(roh, einheit, erwartet):
    assert E.leistung_in_w(roh, einheit) == erwartet


def test_thermische_leistung():
    d = {"par4": 35.0, "par5": 30.0, "par20": 50}
    assert E.thermische_leistung_w(d, "Heizen", 2.0, 1.0) == pytest.approx(2.0 * 5 * 1163)
    assert E.thermische_leistung_w(d, "Brauchwasser", 2.0, 1.0) == pytest.approx(5 * 1163)
    # Live-Volumenstrom gewinnt
    assert E.thermische_leistung_w(d, "Heizen", 2.0, 1.0, 1.5) == pytest.approx(1.5 * 5 * 1163)
    # Kein Waermeeintrag
    assert E.thermische_leistung_w(d, "Entfrosten", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w(d, "Aus", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par20": 0}, "Heizen", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par20": None}, "Heizen", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par5": 36.0}, "Heizen", 2.0, 1.0) == 0.0
    # Fehlende Temperaturen
    assert E.thermische_leistung_w({"par4": 35.0}, "Heizen", 2.0, 1.0) is None
    assert E.thermische_leistung_w(None, "Heizen", 2.0, 1.0) is None


# ── EnergieZaehler ───────────────────────────────────────────────────────

def test_links_rechteck_mit_wert_zu_beginn():
    z = E.EnergieZaehler(15 * 60, E.METHODE_LINKS)
    assert z.messpunkt(0, 1000, E.HEIZEN) == 0.0
    # 1000 W fuer 10 min = 1/6 kWh, gebucht auf Heizen
    assert z.messpunkt(600, 3000, E.WARMWASSER) == pytest.approx(1000 * 600 / 3.6e6)
    # 3000 W fuer 5 min, gebucht auf Warmwasser (Betriebsart zu Beginn)
    z.messpunkt(900, 0, None)
    assert z.summen[E.HEIZEN] == pytest.approx(1000 * 600 / 3.6e6)
    assert z.summen[E.WARMWASSER] == pytest.approx(3000 * 300 / 3.6e6)
    assert z.summen[E.GESAMT] == pytest.approx(z.summen[E.HEIZEN] + z.summen[E.WARMWASSER])


def test_trapez():
    z = E.EnergieZaehler(10 * 60, E.METHODE_TRAPEZ)
    z.messpunkt(0, 0, E.HEIZEN)
    z.messpunkt(60, 6000, E.HEIZEN)
    assert z.summen[E.GESAMT] == pytest.approx(3000 * 60 / 3.6e6)
    assert z.summen[E.HEIZEN] == z.summen[E.GESAMT]


def test_rest_nur_in_gesamtsumme():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 3600, None)
    z.messpunkt(H / 6, 0, None)   # 10 min
    assert z.summen[E.GESAMT] == pytest.approx(0.6)
    assert z.summen[E.HEIZEN] == 0.0
    assert z.summen[E.WARMWASSER] == 0.0


def test_luecke_wird_verworfen():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 2000, E.HEIZEN)
    assert z.messpunkt(16 * 60, 2000, E.HEIZEN) == 0.0
    assert z.summen[E.GESAMT] == 0.0
    # Danach geht es normal weiter
    z.messpunkt(16 * 60 + 360, 2000, E.HEIZEN)
    assert z.summen[E.GESAMT] == pytest.approx(2000 * 360 / 3.6e6)


def test_unavailable_beendet_kette():
    links = E.EnergieZaehler(15 * 60, E.METHODE_LINKS)
    links.messpunkt(0, 1200, E.HEIZEN)
    # Bis zum Ausfall galt der alte Wert noch
    assert links.messpunkt(300, None) == pytest.approx(1200 * 300 / 3.6e6)
    # Nach dem Ausfall: neuer Anfang, nichts nachgebucht
    assert links.messpunkt(600, 1200, E.HEIZEN) == 0.0
    assert links.summen[E.GESAMT] == pytest.approx(1200 * 300 / 3.6e6)

    trapez = E.EnergieZaehler(10 * 60, E.METHODE_TRAPEZ)
    trapez.messpunkt(0, 1200, E.HEIZEN)
    assert trapez.messpunkt(300, None) == 0.0
    assert trapez.messpunkt(400, 1200, E.HEIZEN) == 0.0
    assert trapez.summen[E.GESAMT] == 0.0


def test_zeit_rueckwaerts_bucht_nichts():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(100, 1000, E.HEIZEN)
    assert z.messpunkt(50, 1000, E.HEIZEN) == 0.0
    assert z.summen[E.GESAMT] == 0.0


def test_negative_leistung_zaehlt_nicht_rueckwaerts():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, -500, E.HEIZEN)
    z.messpunkt(60, 0, E.HEIZEN)
    assert z.summen[E.GESAMT] == 0.0


def test_uebernehme_addiert_und_ignoriert_unsinn():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 3600, E.HEIZEN)
    z.messpunkt(H / 6, 0, E.HEIZEN)
    z.uebernehme(E.GESAMT, 100.0)
    z.uebernehme(E.HEIZEN, "40.5")
    z.uebernehme(E.WARMWASSER, "kaputt")
    z.uebernehme(E.WARMWASSER, -3)
    assert z.summen[E.GESAMT] == pytest.approx(100.6)
    assert z.summen[E.HEIZEN] == pytest.approx(41.1)
    assert z.summen[E.WARMWASSER] == 0.0
    with pytest.raises(KeyError):
        z.uebernehme("kuehlen", 1)


def test_unbekannte_methode():
    with pytest.raises(ValueError):
        E.EnergieZaehler(60, "simpson")


def test_slugs_der_zaehler():
    slugs = [s for s, _, _ in E.ENERGIE_ZAEHLER]
    assert slugs == [
        "energie_elektrisch", "energie_elektrisch_heizen", "energie_elektrisch_warmwasser",
        "energie_elektrisch_standby",
        "energie_thermisch", "energie_thermisch_heizen", "energie_thermisch_warmwasser",
    ]


# ── ZaehlerstandFolger (Stromzaehler statt Leistung, v4.0.1) ─────────────

@pytest.mark.parametrize("roh, einheit, erwartet", [
    ("12.5", "kWh", 12.5),
    ("12500", "Wh", 12.5),
    ("0.0125", "MWh", 12.5),
    ("12.5", None, 12.5),
    ("12.5", "KWH", 12.5),
    ("12.5", "W", None),           # keine Energieeinheit
    ("unavailable", "kWh", None),
    ("unknown", "kWh", None),
    ("", "kWh", None),
    ("nan", "kWh", None),
])
def test_energie_in_kwh(roh, einheit, erwartet):
    wert = E.energie_in_kwh(roh, einheit)
    assert wert == (pytest.approx(erwartet) if erwartet is not None else None)


def test_zaehlerstand_deltas_nach_betriebsart():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    assert f.messpunkt(0, 1000.0, E.HEIZEN) == 0.0          # erster Stand = Basis
    assert f.messpunkt(600, 1000.4, E.HEIZEN) == pytest.approx(0.4)
    assert f.messpunkt(900, 1000.5, E.WARMWASSER) == pytest.approx(0.1)
    assert f.messpunkt(1200, 1000.7, None) == pytest.approx(0.2)
    assert z.summen[E.GESAMT] == pytest.approx(0.7)
    assert z.summen[E.HEIZEN] == pytest.approx(0.4)
    assert z.summen[E.WARMWASSER] == pytest.approx(0.1)


def test_zaehlerstand_unavailable_wird_ignoriert():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.messpunkt(0, 50.0, E.HEIZEN)
    assert f.messpunkt(60, None, E.HEIZEN) == 0.0
    # Der Zuwachs ueber den Ausfall hinweg zaehlt - der Zaehler lief weiter
    assert f.messpunkt(3600, 51.0, E.HEIZEN) == pytest.approx(1.0)
    assert z.summen[E.HEIZEN] == pytest.approx(1.0)


def test_zaehlerstand_reset_und_gleichstand():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.messpunkt(0, 500.0)
    assert f.messpunkt(60, 500.0) == 0.0
    assert f.messpunkt(120, 0.2) == 0.0       # Reset: verwerfen, neue Basis
    assert f.basis == pytest.approx(0.2)
    assert f.messpunkt(3600, 0.9) == pytest.approx(0.7)
    assert z.summen[E.GESAMT] == pytest.approx(0.7)


def test_zaehlerstand_unglaubwuerdiger_sprung():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.messpunkt(0, 10.0)
    # 1000 kWh in einer Minute: Zaehlertausch, kein Verbrauch
    assert f.messpunkt(60, 1010.0) == 0.0
    assert f.basis == pytest.approx(1010.0)
    assert f.messpunkt(120, 1010.05) == pytest.approx(0.05)


def test_zaehlerstand_basis_wiederherstellen():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.setze_basis("abc")
    assert f.basis is None
    f.setze_basis("100.0", 0)
    f.setze_basis("999.0", 0)                  # zweite Basis wird nicht uebernommen
    assert f.basis == pytest.approx(100.0)
    # Verbrauch waehrend des Neustarts zaehlt
    assert f.messpunkt(300, 100.3, E.HEIZEN) == pytest.approx(0.3)


def test_zaehlerstand_basis_nach_erstem_messpunkt():
    # Beobachtung startet vor der Wiederherstellung: der erste Live-Stand wird
    # von der gespeicherten Basis ersetzt, solange nichts gebucht ist.
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.messpunkt(300, 100.3, E.HEIZEN)
    f.setze_basis(100.0, 0)
    assert f.messpunkt(360, 100.4, E.HEIZEN) == pytest.approx(0.4)
    f.setze_basis(50.0, 0)                     # nach einer Buchung wirkungslos
    assert f.basis == pytest.approx(100.4)


def test_analyse_konfiguration_registry_und_rueckfall():
    registry = {
        ("sensor", "es_heatpump_hans@x.de_calc_energie_elektrisch"): "sensor.wp_strom_zaehler",
        ("sensor", "es_heatpump_hans@x.de_par24"): "sensor.draussen",
        ("binary_sensor", "es_heatpump_hans@x.de_takten"): "binary_sensor.wp_taktet",
        # gleiche unique_id auf anderer Plattform darf nicht treffen
        ("sensor", "es_heatpump_hans@x.de_verdichter"): "sensor.falsch",
    }

    def finde(unique_id, plattform="sensor"):
        return registry.get((plattform, unique_id))

    a = E.analyse_konfiguration(
        finde, "hans@x.de",
        {"energy_entity": "sensor.shelly_energy", "power_entity": "", "flow_entity": "x"},
    )
    assert a["counters"]["el"] == "sensor.wp_strom_zaehler"
    assert a["counters"]["th_dhw"] == "sensor.es_hp_energie_thermisch_warmwasser"
    assert a["counters"]["runtime"] == "sensor.es_hp_verdichter_laufzeit"
    assert set(a["counters"]) == {"el", "el_heat", "el_dhw", "el_standby", "th", "th_heat",
                                  "th_dhw", "starts", "runtime"}
    assert a["counters"]["el_standby"] == "sensor.es_hp_energie_elektrisch_standby"
    # v4.1.0: Binaersensoren und Carnot-Guetegrad
    assert a["binary"] == {
        "verdichter": "binary_sensor.es_hp_verdichter",
        "abtauen": "binary_sensor.es_hp_abtauen",
        "warmwasser": "binary_sensor.es_hp_warmwasserbereitung",
        "takten": "binary_sensor.wp_taktet",
    }
    assert a["carnot"] == "sensor.es_hp_carnot_guetegrad"
    assert a["outdoor"] == "sensor.draussen"
    assert a["electrical_power"] == "sensor.es_hp_leistung_elektrisch"
    assert a["thermal_power"] == "sensor.es_hp_thermische_leistung"
    assert a["cop"] == "sensor.es_hp_aktueller_cop"
    assert a["flow"] == "sensor.es_hp_vorlauf_tuo"
    assert a["energy_entity"] == "sensor.shelly_energy"
    assert a["power_entity"] is None
    # Zaehler-Slugs passen zu den Entities der Integration
    assert set(E.ANALYSE_ZAEHLER.values()) >= {slug for slug, _, _ in E.ENERGIE_ZAEHLER}
    # Ohne Eintrag: nur Standard-IDs
    leer = E.analyse_konfiguration(lambda _u, _p="sensor": None, None, {})
    assert leer["counters"]["el"] == "sensor.es_hp_energie_elektrisch"
    assert leer["energy_entity"] is None
    assert leer["binary"]["takten"] == "binary_sensor.es_hp_takten"


# ── VerdichterZaehler ────────────────────────────────────────────────────

def test_verdichter_starts_und_laufzeit():
    v = E.VerdichterZaehler(10 * 60)
    v.messpunkt(0, 0)
    assert v.messpunkt(60, 45) is True          # Start
    assert v.starts == 1
    v.messpunkt(120, 50)                        # laeuft weiter, kein Start
    v.messpunkt(180, 0)                         # stoppt
    assert v.starts == 1
    assert v.laufzeit_h == pytest.approx(120 / H)
    v.messpunkt(240, 30)
    assert v.starts == 2


def test_verdichter_erster_messpunkt_ist_kein_start():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 50)
    assert v.starts == 0
    v.messpunkt(60, 50)
    assert v.laufzeit_h == pytest.approx(60 / H)


def test_verdichter_fehlender_wert_zaehlt_keinen_start():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    v.messpunkt(60, 40)
    v.messpunkt(120, None)
    v.messpunkt(180, 40)
    assert v.starts == 1
    assert v.laufzeit_h == pytest.approx(120 / H)   # 60..180 s gelaufen


def test_verdichter_luecke():
    v = E.VerdichterZaehler(10 * 60)
    v.messpunkt(0, 40)
    v.messpunkt(11 * 60, 40)
    assert v.laufzeit_h == 0.0
    v.messpunkt(12 * 60, 0)
    v.messpunkt(30 * 60, 40)    # Start ueber eine Luecke hinweg zaehlt trotzdem
    assert v.starts == 1


def test_verdichter_uebernehme():
    v = E.VerdichterZaehler()
    v.uebernehme(starts="12", laufzeit_h=3.5)
    v.uebernehme(starts="x", laufzeit_h=None)
    assert v.starts == 12
    assert v.laufzeit_h == pytest.approx(3.5)


# ── Aenderungsverlauf aus den Sicherungen ────────────────────────────────

def _bekannte_schreibbare(n):
    return [p for p, s in S.SETTINGS.items() if s.writable][:n]


def _sicherung(kennung, zeit, pars, anlass=B.ANLASS_AUTOMATISCH):
    return B.Sicherung(id=kennung, zeitpunkt=zeit, anlass=anlass, pars=dict(pars))


def test_aenderungsverlauf():
    p1, p2 = _bekannte_schreibbare(2)
    basis = {p1: 1, p2: 0, "par999": 5}
    s1 = _sicherung("a", "2026-01-01T10:00:00+01:00", basis, B.ANLASS_ERSTE)
    s2 = _sicherung("b", "2026-01-02T10:00:00+01:00", {**basis, "par999": 6})    # nur unbenannt
    s3 = _sicherung("c", "2026-01-03T10:00:00+01:00", {**basis, p2: 1, "par999": 6},
                    B.ANLASS_VOR_SCHREIBEN)
    s4 = _sicherung("d", "2026-01-04T10:00:00+01:00", {**basis, p2: 1, "par999": 6})  # gleich
    # Reihenfolge der Eingabe egal (Ablage liefert neueste zuerst)
    verlauf = B.aenderungsverlauf([s4, s2, s3, s1])
    assert len(verlauf) == 1
    eintrag = verlauf[0]
    assert eintrag["time"] == "2026-01-03T09:00:00+00:00"
    assert eintrag["reason"] == B.ANLASS_VOR_SCHREIBEN
    assert len(eintrag["items"]) == 1
    posten = eintrag["items"][0]
    assert posten["par"] == p2
    assert posten["old"] == 0 and posten["new"] == 1
    assert posten["name"] == S.SETTINGS[p2].name
    assert posten["group"] == S.SETTINGS[p2].group
    assert S.SETTINGS[p2].name in posten["text"] and "→" in posten["text"]


def test_aenderungsverlauf_mit_unbenannten_feldern():
    s1 = _sicherung("a", "2026-01-01T10:00:00+00:00", {"par999": 5})
    s2 = _sicherung("b", "2026-01-02T10:00:00+00:00", {"par999": 6})
    assert B.aenderungsverlauf([s1, s2]) == []
    verlauf = B.aenderungsverlauf([s1, s2], nur_bekannte=False)
    assert verlauf[0]["items"][0]["group"] == "Ohne Katalogeintrag"


def test_aenderungsverlauf_leer_und_einzeln():
    assert B.aenderungsverlauf([]) == []
    assert B.aenderungsverlauf([_sicherung("a", "2026-01-01T10:00:00+00:00", {"par1": 1})]) == []


def test_aenderungsverlauf_feld_entfernt():
    p1 = _bekannte_schreibbare(1)[0]
    s1 = _sicherung("a", "2026-01-01T10:00:00", {p1: 1})          # ohne Zone -> UTC
    s2 = _sicherung("b", "2026-01-02T10:00:00", {})
    verlauf = B.aenderungsverlauf([s1, s2])
    assert verlauf[0]["time"] == "2026-01-02T10:00:00+00:00"
    assert verlauf[0]["items"][0]["new"] is None
    assert verlauf[0]["items"][0]["text"].endswith("→ -")


# ── Standby-Zaehler (v4.1.0) ─────────────────────────────────────────────

@pytest.mark.parametrize("frequenz, erwartet", [
    (0, True), (0.0, True), ("0", True), (-1, True),
    (35, False), ("42.5", False), (None, False), ("x", False), (float("nan"), False),
])
def test_verdichter_steht(frequenz, erwartet):
    assert E.verdichter_steht(frequenz) is erwartet


def test_standby_bei_leistungsintegration():
    """Links integriert: Standby gilt fuer das Intervall ab dem Messpunkt."""
    z = E.EnergieZaehler(15 * 60, E.METHODE_LINKS)
    z.messpunkt(0, 3600, E.HEIZEN, standby=False)       # Verdichter laeuft
    z.messpunkt(60, 36, E.HEIZEN, standby=True)         # 60 s x 3600 W = 0,06 kWh
    z.messpunkt(120, 36, None, standby=True)            # 60 s x 36 W
    z.messpunkt(180, 3600, E.HEIZEN, standby=False)     # 60 s x 36 W
    z.messpunkt(240, None)                              # 60 s x 3600 W, Kette endet
    assert z.summen[E.GESAMT] == pytest.approx(0.12 + 2 * 0.0006)
    assert z.summen[E.STANDBY] == pytest.approx(2 * 0.0006)
    # Standby ist ein Querschnitt: Intervall 60..120 (Heizen) zaehlt auch dort
    assert z.summen[E.HEIZEN] == pytest.approx(0.12 + 0.0006)


def test_standby_bei_zaehlerstaenden():
    z = E.EnergieZaehler(15 * 60)
    f = E.ZaehlerstandFolger(z)
    f.messpunkt(0, 100.0, None, True)
    assert f.messpunkt(600, 100.01, None, True) == pytest.approx(0.01)
    f.messpunkt(1200, 100.31, E.HEIZEN, False)
    f.messpunkt(1800, 100.32, E.HEIZEN, True)
    assert z.summen[E.GESAMT] == pytest.approx(0.32)
    assert z.summen[E.STANDBY] == pytest.approx(0.02)
    assert z.summen[E.HEIZEN] == pytest.approx(0.31)


def test_standby_wiederherstellen():
    z = E.EnergieZaehler(60)
    z.uebernehme(E.STANDBY, "1.25")
    assert z.summen[E.STANDBY] == pytest.approx(1.25)
    assert z.summen[E.GESAMT] == 0.0


def test_standby_zaehler_ist_elektrisch():
    eintraege = {slug: (art, teil) for slug, art, teil in E.ENERGIE_ZAEHLER}
    assert eintraege["energie_elektrisch_standby"] == (E.ART_ELEKTRISCH, E.STANDBY)


# ── Takt-Erkennung (v4.1.0) ──────────────────────────────────────────────

def _zyklen(v, t0, anzahl, lauf_s, pause_s, takt_s=60):
    """``anzahl`` Zyklen Lauf/Pause im Abruftakt ``takt_s``; liefert das Ende."""
    t = t0
    for _ in range(anzahl):
        ende = t + lauf_s
        while t < ende:
            v.messpunkt(t, 40)
            t += takt_s
        ende = t + pause_s
        while t < ende:
            v.messpunkt(t, 0)
            t += takt_s
    return t


def test_takt_schwellen():
    assert E.TAKT_MAX_STARTS_JE_STUNDE == 3
    assert E.TAKT_MIN_LAUFZEIT_MIN == 10
    assert E.TAKT_ZYKLEN == 3


def test_takt_lange_zyklen_unauffaellig():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    t = _zyklen(v, 60, 3, 40 * 60, 20 * 60)
    assert v.starts == 3
    assert v.mittlere_laufzeit_min() == pytest.approx(40)
    assert v.starts_seit(t) <= 1
    assert v.taktet(t) is False


def test_takt_viele_starts_je_stunde():
    # 4 Starts in 48 min, je 11 min Lauf - das Laufzeit-Kriterium allein waere ok
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    t = _zyklen(v, 60, 4, 11 * 60, 60)
    assert v.starts == 4
    assert v.starts_seit(t) == 4
    assert v.mittlere_laufzeit_min() >= 10
    assert v.taktet(t) is True
    # Genau 3 Starts sind noch erlaubt
    assert v.taktet(t, max_starts=4) is False
    # Eine Stunde spaeter faellt alles aus dem Fenster
    assert v.starts_seit(t + 3600) == 0
    assert v.taktet(t + 3600) is False


def test_takt_kurze_laufzeit():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    t = _zyklen(v, 60, 3, 5 * 60, 40 * 60)       # 3 x 5 min, weit auseinander
    assert v.starts_seit(t) <= 2
    assert v.mittlere_laufzeit_min() == pytest.approx(5)
    assert v.taktet(t) is True
    # Steht der Verdichter danach laenger als die Altersgrenze, ist es vorbei
    assert v.taktet(t + E.TAKT_ZYKLEN_MAX_ALTER_S + 3600) is False


def test_takt_braucht_drei_zyklen():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    t = _zyklen(v, 60, 2, 5 * 60, 40 * 60)
    assert v.mittlere_laufzeit_min() is None
    assert v.taktet(t) is False


def test_takt_zyklus_ohne_bekannten_beginn_zaehlt_nicht():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 40)            # erster Messpunkt: laeuft schon
    v.messpunkt(60, 0)            # Stopp - Laenge unbekannt
    assert v.mittlere_laufzeit_min(1) is None
    v.messpunkt(120, 40)
    v.messpunkt(180, 40)
    v.messpunkt(240, None)        # Aussetzer: kein Stopp
    v.messpunkt(300, 0)
    assert v.mittlere_laufzeit_min(1) == pytest.approx(3)


def test_takt_luecke_verwirft_zyklus():
    v = E.VerdichterZaehler(10 * 60)
    v.messpunkt(0, 0)
    v.messpunkt(60, 40)
    v.messpunkt(60 + 11 * 60, 40)     # Luecke im Lauf
    v.messpunkt(60 + 12 * 60, 0)
    assert v.mittlere_laufzeit_min(1) is None


def test_takt_ringpuffer_begrenzt():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    _zyklen(v, 60, 50, 60, 60)
    assert len(v._start_zeiten) <= 32 and len(v._zyklen_s) <= 10
    assert v.starts == 50


# ── Carnot-Guetegrad (v4.1.0) ────────────────────────────────────────────

def test_cop_carnot_formel():
    # Vorlauf 35, aussen 7: (37 + 273,15) / (37 - 1) = 8,615...
    assert E.cop_carnot(35, 7) == pytest.approx(310.15 / 36)
    assert E.CARNOT_OFFSET_KONDENSATION_K == 2.0
    assert E.CARNOT_OFFSET_VERDAMPFUNG_K == -6.0


@pytest.mark.parametrize("vor, aussen", [
    (None, 5), (35, None), ("x", 5), (-99, 5), (35, -99.0), (float("inf"), 5),
])
def test_cop_carnot_ungueltig(vor, aussen):
    assert E.cop_carnot(vor, aussen) is None


def test_cop_carnot_aussen_waermer_als_vorlauf():
    # Nenner (20 + 2) - (25 - 6) = 3 K: noch gerechnet
    assert E.cop_carnot(20, 25) == pytest.approx(295.15 / 3)


def test_cop_carnot_nenner_zu_klein():
    # (T_vor + 2) - (T_aussen - 6) = 1 K -> None; 1,5 K -> gerechnet
    assert E.cop_carnot(10, 17) is None
    assert E.cop_carnot(10, 18) is None
    assert E.cop_carnot(10.5, 17) == pytest.approx((12.5 + 273.15) / 1.5)


def test_carnot_guetegrad():
    guete, ideal = E.carnot_guetegrad(4.0, 35, 7, True)
    assert ideal == pytest.approx(310.15 / 36)
    assert guete == pytest.approx(4.0 / (310.15 / 36) * 100)
    assert 40 < guete < 50


@pytest.mark.parametrize("cop, laeuft", [
    (4.0, False), (4.0, None), (0, True), (-1, True), (None, True), ("x", True),
])
def test_carnot_guetegrad_none(cop, laeuft):
    guete, ideal = E.carnot_guetegrad(cop, 35, 7, laeuft)
    assert guete is None
    assert ideal == pytest.approx(310.15 / 36)


def test_carnot_guetegrad_ohne_carnot():
    assert E.carnot_guetegrad(4.0, 35, None, True) == (None, None)
