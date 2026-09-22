"""Tests für die Sicherungslogik und die Stammdaten (v3.0.0).

Geprüft wird die reine Logik – Vergleich, Aufräumen, Wiederherstellungsplan,
Prüfsummen – ohne Home Assistant.

Aufruf:  python3 -m pytest tests/ -q
   oder:  python3 tests/test_backup.py
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
    voll = f"{_PKG}.{name}"
    if voll in sys.modules:
        return sys.modules[voll]
    spec = importlib.util.spec_from_file_location(voll, _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[voll] = modul
    spec.loader.exec_module(modul)
    return modul


_lade("settings")
B = _lade("backup")
M = _lade("metadata")


def _sicherung(kennung, zeit, anlass=B.ANLASS_AUTOMATISCH, pars=None):
    return B.Sicherung(
        id=kennung, zeitpunkt=zeit, anlass=anlass, pars=pars or {"par1": 1}
    )


# ── Prüfsummen ───────────────────────────────────────────────────────────

def test_pruefsumme_ignoriert_reihenfolge_und_zahlentyp():
    """Sonst entstünde bei jedem Abruf eine neue Sicherung."""
    a = B.pruefsumme_von({"par1": 1, "par2": 218})
    b = B.pruefsumme_von({"par2": 218.0, "par1": 1.0})
    assert a == b


def test_pruefsumme_erkennt_aenderung():
    a = B.pruefsumme_von({"par55": 50})
    b = B.pruefsumme_von({"par55": 51})
    assert a != b


# ── Vergleich ────────────────────────────────────────────────────────────

def test_vergleich_findet_geaenderte_werte():
    abw = B.vergleiche({"par55": 50, "par1": 1}, {"par55": 52, "par1": 1})
    assert len(abw) == 1
    assert abw[0].par == "par55"
    assert abw[0].vorher == 50 and abw[0].nachher == 52
    assert abw[0].name == "Warmwasser Solltemperatur"
    assert abw[0].schreibbar is True


def test_vergleich_meldet_neue_und_entfallene_felder():
    """Ein Portal-Umbau soll sichtbar werden, nicht stillschweigend passieren."""
    abw = B.vergleiche({"par55": 50}, {"par55": 50, "par999": 3})
    assert len(abw) == 1
    assert abw[0].par == "par999"
    assert abw[0].vorher is None and abw[0].nachher == 3
    assert abw[0].bekannt is False


def test_vergleich_ist_nach_feldnummer_sortiert():
    abw = B.vergleiche({}, {"par100": 1, "par9": 1, "par20": 1})
    assert [a.par for a in abw] == ["par9", "par20", "par100"]


# ── Aufräumen ────────────────────────────────────────────────────────────

def test_aufraeumen_behaelt_die_juengsten():
    liste = [_sicherung(f"s{i}", f"2026-09-{10+i:02d}T10:00:00") for i in range(5)]
    bleiben, weg = B.aufraeumen(liste, behalten=3)
    assert len(bleiben) == 3 and len(weg) == 2
    assert [s.id for s in bleiben] == ["s4", "s3", "s2"]


def test_aufraeumen_schont_eingriffs_sicherungen():
    """Der Stand *vor* einem Eingriff ist der, den man später sucht.

    Er ist zwangsläufig älter als die Sicherungen danach und fiele einem
    reinen Zeitfenster als Erstes zum Opfer.
    """
    liste = [
        _sicherung("alt", "2026-01-01T10:00:00", B.ANLASS_VOR_SCHREIBEN),
        _sicherung("erste", "2026-01-01T09:00:00", B.ANLASS_ERSTE),
        *[_sicherung(f"n{i}", f"2026-09-{10+i:02d}T10:00:00") for i in range(5)],
    ]
    bleiben, weg = B.aufraeumen(liste, behalten=2)
    kennungen = {s.id for s in bleiben}
    assert "alt" in kennungen and "erste" in kennungen
    assert len(weg) == 3
    assert all(s.anlass == B.ANLASS_AUTOMATISCH for s in weg)


def test_aufraeumen_abschaltbar():
    liste = [_sicherung(f"s{i}", f"2026-09-{10+i:02d}T10:00:00") for i in range(9)]
    bleiben, weg = B.aufraeumen(liste, behalten=0)
    assert len(bleiben) == 9 and not weg


# ── Wiederherstellungsplan ───────────────────────────────────────────────

def test_plan_schreibt_nur_bedienbare_felder():
    """Von 300 gesicherten Feldern sind 70 überhaupt schreibbar."""
    jetzt = {"par55": 45, "par2": 218, "par203": 0}
    ziel  = {"par55": 50, "par2": 300, "par203": 7}
    plan = B.plane_wiederherstellung(jetzt, ziel)
    assert [a.par for a in plan.zu_schreiben] == ["par55"]
    uebersprungen = {a.par for a in plan.uebersprungen}
    assert uebersprungen == {"par2", "par203"}


def test_plan_nennt_den_grund_fuer_jedes_uebersprungene_feld():
    plan = B.plane_wiederherstellung({"par2": 218}, {"par2": 300})
    d = plan.als_dict()
    assert d["anzahl_schreibvorgaenge"] == 0
    assert "Nur-Lese-Wert" in d["uebersprungen"][0]["warum"]


def test_plan_faengt_werte_ausserhalb_des_bereichs_ab():
    """Eine beschädigte Sicherung darf keine unmöglichen Werte schreiben."""
    plan = B.plane_wiederherstellung({"par55": 50}, {"par55": 900})
    assert not plan.zu_schreiben
    assert plan.uebersprungen[0].par == "par55"


def test_plan_ist_leer_wenn_nichts_abweicht():
    plan = B.plane_wiederherstellung({"par55": 50}, {"par55": 50})
    assert plan.anzahl == 0 and not plan.uebersprungen


# ── Sicherung selbst ─────────────────────────────────────────────────────

def test_sicherung_berechnet_pruefsumme_selbst():
    s = B.Sicherung(id="x", zeitpunkt="2026-09-22T08:00:00", anlass="manuell",
                    pars={"par55": 50})
    assert s.pruefsumme == B.pruefsumme_von({"par55": 50})
    assert s.anzahl == 1


def test_lesbare_fassung_laesst_unbenannte_felder_weg():
    """226 Zeilen "par203 = 0" wären keine Übersicht."""
    s = B.Sicherung(id="x", zeitpunkt="t", anlass="manuell",
                    pars={"par55": 50, "par203": 0})
    lesbar = s.lesbar()
    assert len(lesbar) == 1
    # par55 steht im Portal unter "Quick Setting", nicht unter "DHW Settings"
    assert "Schnelleinstellung / Warmwasser Solltemperatur" in lesbar
    assert lesbar["Schnelleinstellung / Warmwasser Solltemperatur"] == "50 °C"


def test_rundreise_durch_die_ablage():
    s = B.Sicherung(id="x", zeitpunkt="t", anlass="manuell", pars={"par55": 50},
                    stammdaten={"modell": "AW12"}, version="3.0.0")
    zurueck = B.aus_dict({**s.__dict__, "unbekanntes_feld": "egal"})
    assert zurueck.id == "x" and zurueck.pars == {"par55": 50}
    assert zurueck.stammdaten == {"modell": "AW12"}


# ── Stammdaten ───────────────────────────────────────────────────────────
#
# ALLE WERTE HIER SIND ERFUNDEN. Seriennummern, MAC-Adresse, Portal-Kennung,
# Anschrift, Namen und Datumsangaben sind frei gewaehlte Beispiele in dem
# Format, das das Portal liefert - sie gehoeren zu keiner realen Anlage.
# Wer diese Datei erweitert: bitte so halten. Testdaten aus einer echten
# Anlage landen sonst dauerhaft in der Versionsgeschichte eines oeffentlichen
# Repositoriums.

_GERAET = {
    "devicetype": "AW12-R32-M-V8",
    "devicenum": "230101-240117-0042",
    "mac": "A1B2C3D4E5F6",
    "mn": 99999, "devid": 1,
    "firstruntime": "2024-01-17",
    "warrantyperiod": "2029-01-17",
    "address": "Germany, 12345 Musterstadt",
    "note": "AW12-R32-M-V8 IG: 230098-240115-0041 AG: 230101-240117-0042",
    "office": {"officeName": "Musterheizung GmbH", "officeCode": "OEM00000000"},
    "user": {"userName": "Erika Mustermann"},
}


def test_stammdaten_aus_geraeteliste():
    s = M.aus_geraeteliste(_GERAET)
    assert s.modell == "AW12-R32-M-V8"
    assert s.mac == "A1B2C3D4E5F6"
    assert s.garantie_bis == "2029-01-17"
    assert s.installateur == "Musterheizung GmbH"
    assert s.besitzer == "Erika Mustermann"


def test_beide_seriennummern_werden_getrennt():
    """Innen- und Außengerät haben verschiedene Nummern; devicenum nennt nur eine."""
    s = M.aus_geraeteliste(_GERAET)
    assert s.seriennummer_innengeraet == "230098-240115-0041"
    assert s.seriennummer_aussengeraet == "230101-240117-0042"
    assert s.seriennummer_innengeraet != s.seriennummer_aussengeraet


def test_stammdaten_ueberleben_ein_leeres_geraet():
    """Ein Portal-Umbau darf Lücken hinterlassen, nie einen Absturz."""
    s = M.aus_geraeteliste({})
    assert s.modell is None
    assert s.als_dict() == {}
    assert s.garantie_restjahre is None


def test_garantie_restlaufzeit():
    s = M.Stammdaten(garantie_bis="2029-01-17")
    assert s.garantie_restjahre > 0
    abgelaufen = M.Stammdaten(garantie_bis="2020-01-01")
    assert abgelaufen.garantie_restjahre < 0
    assert M.Stammdaten(garantie_bis="kein Datum").garantie_restjahre is None


def test_formularkopf_ergaenzt_installateur_und_artikelnummer():
    kopf = (
        '<div class="box-content mb10"> MAC：A1B2C3D4E5F6 &nbsp;&nbsp; '
        "Binding user：Erika Mustermann &nbsp;&nbsp; Installer：Musterheizung GmbH &nbsp;&nbsp; "
        "Unit Model No.：AW12-R32-M-V8 &nbsp;&nbsp; "
        "Unit Serial No.：230101-240117-0042 &nbsp;&nbsp; "
        "Article No.：AB-4711 &nbsp;&nbsp; Start-Up：2024-01-17 00:00 &nbsp;&nbsp; "
        "Warranty Period：2029-01-17 </div>"
    )
    s = M.aus_formularkopf(kopf)
    assert s.artikelnummer == "AB-4711"
    assert s.installateur == "Musterheizung GmbH"
    # Werte mit Leerzeichen bleiben ganz
    assert s.inbetriebnahme == "2024-01-17 00:00"


def test_formularkopf_ueberschreibt_nichts_vorhandenes():
    vorher = M.Stammdaten(modell="aus der Geräteliste")
    s = M.aus_formularkopf(
        '<div class="box-content mb10"> Unit Model No.：ANDERS </div>', vorher
    )
    assert s.modell == "aus der Geräteliste"


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
