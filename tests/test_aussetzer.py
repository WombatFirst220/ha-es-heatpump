"""Tests für die Erkennung von Portal-Aussetzern (v4.0.1).

Am 20.10.2026 um 01:43 lieferte das Portal einen Konfigurationsstand, in dem
fast alle Werte 0 waren (Softwareversion 218 → 0, Datenbankversion 115 → 0
und 56 weitere), um 01:58 wieder den echten. Beide Stände wurden gesichert
und erschienen als zwei "Änderungen" mit je 58 Posten.

Geprüft wird ohne Home Assistant: die Plausibilitätsfunktion und der
Änderungsverlauf (``backup.py``) direkt, Ablage und Konfigurations-Koordinator
mit kleinen Attrappen der wenigen HA-Klassen, die sie benutzen.

Aufruf:  python3 -m pytest tests/ -q
"""
import asyncio
import datetime
import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_aussetzer_test"


# ── Attrappen für Home Assistant (nur, was Ablage und Koordinator brauchen) ──

class _Store:
    """In-Memory-Ersatz für helpers.storage.Store."""

    def __init__(self, hass, version, key, private=False):
        self.daten = None
        self.gespeichert = 0

    async def async_load(self):
        return self.daten

    async def async_save(self, daten):
        self.daten = daten
        self.gespeichert += 1


class _UpdateFailed(Exception):
    pass


class _DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None

    def __class_getitem__(cls, item):
        return cls

    def async_set_updated_data(self, data):
        self.data = data


_JETZT = [datetime.datetime(2026, 10, 20, 1, 30, tzinfo=datetime.timezone.utc)]


def _stubs():
    mods = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.exceptions": types.ModuleType("homeassistant.exceptions"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.storage": types.ModuleType("homeassistant.helpers.storage"),
        "homeassistant.helpers.update_coordinator": types.ModuleType(
            "homeassistant.helpers.update_coordinator"),
        "homeassistant.util": types.ModuleType("homeassistant.util"),
        "homeassistant.util.dt": types.ModuleType("homeassistant.util.dt"),
    }
    mods["homeassistant.core"].HomeAssistant = object
    mods["homeassistant.exceptions"].ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    mods["homeassistant.helpers.storage"].Store = _Store
    mods["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _DataUpdateCoordinator
    mods["homeassistant.helpers.update_coordinator"].UpdateFailed = _UpdateFailed
    dt = mods["homeassistant.util.dt"]
    dt.now = lambda: _JETZT[0]
    dt.parse_datetime = datetime.datetime.fromisoformat
    mods["homeassistant.util"].dt = dt
    return mods


def _lade_alles():
    """Lädt backup, backup_store und settings_coordinator mit Attrappen.

    Die Attrappen stehen nur während des Ladens in ``sys.modules`` - andere
    Tests sehen danach wieder den echten Zustand (kein Home Assistant).
    """
    stubs = _stubs()
    vorher = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        paket = types.ModuleType(_PKG)
        paket.__path__ = [str(_ROOT)]
        sys.modules[_PKG] = paket
        # Der Messwert-Koordinator zieht halb Home Assistant nach sich - fuer
        # diese Tests reicht ein Platzhalter.
        koord = types.ModuleType(f"{_PKG}.coordinator")
        koord.ESHeatpumpCoordinator = object
        sys.modules[f"{_PKG}.coordinator"] = koord
        geladen = {}
        for name in ("settings", "const", "backup", "backup_store", "settings_coordinator"):
            voll = f"{_PKG}.{name}"
            spec = importlib.util.spec_from_file_location(voll, _ROOT / f"{name}.py")
            modul = importlib.util.module_from_spec(spec)
            sys.modules[voll] = modul
            spec.loader.exec_module(modul)
            geladen[name] = modul
        return geladen
    finally:
        for k, v in vorher.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


_M = _lade_alles()
B = _M["backup"]
ST = _M["backup_store"]
SC = _M["settings_coordinator"]

# Der echte Stand vor dem Aussetzer (alle Katalogwerte ungleich 0, aus dem
# Änderungsverlauf der Anlage) plus ein paar Felder ohne Katalogeintrag.
ECHT = {
    "par1": 1, "par2": 218, "par3": 115, "par4": 4, "par5": 2, "par9": 1, "par11": 20,
    "par12": 25, "par20": 3, "par21": 4, "par22": 2, "par23": 20, "par24": 1,
    "par25": -12, "par26": -5, "par28": 5, "par29": 12, "par30": 42, "par31": 40,
    "par32": 37, "par33": 33, "par34": 30, "par36": 23, "par37": 24, "par38": 40,
    "par42": 65, "par43": 20, "par44": 60, "par46": 10, "par47": 10, "par49": 1,
    "par51": 1, "par52": 200, "par53": 30, "par55": 50, "par56": 5, "par58": 15,
    "par59": 15, "par60": 90, "par61": 6, "par63": 1, "par64": 1, "par65": 50,
    "par66": 5, "par68": 24, "par70": 40, "par71": 37, "par72": 34, "par73": 30,
    "par74": 28, "par75": 40, "par79": 2, "par81": 2, "par85": 1, "par86": 1,
    "par121": -1, "par137": 272, "par138": 67029,
    "par203": 7, "par250": 0,
}
AUSSETZER = {k: 0 for k in ECHT}


def _s(kennung, zeit, pars, anlass=B.ANLASS_AUTOMATISCH):
    return B.Sicherung(id=kennung, zeitpunkt=zeit, anlass=anlass, pars=dict(pars))


# ── pruefe_stand ─────────────────────────────────────────────────────────

def test_aussetzer_wird_erkannt():
    grund = B.pruefe_stand(AUSSETZER, ECHT)
    assert grund is not None and "par2" in grund


def test_echter_stand_ist_plausibel():
    assert B.pruefe_stand(ECHT, ECHT) is None
    assert B.pruefe_stand(ECHT) is None


def test_normale_aenderungen_sind_plausibel():
    """Anlage aus (par1 1 → 0) und ein paar Werte auf 0 sind echte Eingriffe."""
    neu = {**ECHT, "par1": 0, "par121": 0, "par20": 0, "par21": 0}
    assert B.pruefe_stand(neu, ECHT) is None


def test_softwareversion_auf_null_allein_reicht():
    assert B.pruefe_stand({**ECHT, "par3": 0}, ECHT) is not None
    assert B.pruefe_stand({k: v for k, v in ECHT.items() if k != "par2"}, ECHT) is not None


def test_viele_katalogwerte_gleichzeitig_auf_null():
    """Auch ohne Systemfelder: die Hälfte der gesetzten Werte auf einmal 0."""
    ohne_system = {k: v for k, v in ECHT.items() if k not in ("par2", "par3")}
    gesetzt = [k for k in ohne_system if k in B.SETTINGS and ohne_system[k] != 0]
    neu = dict(ohne_system)
    for k in gesetzt[: len(gesetzt) // 2 + 1]:
        neu[k] = 0
    assert B.pruefe_stand(neu, ohne_system) is not None
    # neun Werte auf 0 sind noch ein (grosser) Eingriff, kein Aussetzer
    neu = dict(ohne_system)
    for k in gesetzt[:9]:
        neu[k] = 0
    assert B.pruefe_stand(neu, ohne_system) is None


def test_ohne_vorstand_nur_wenn_alles_null():
    assert B.pruefe_stand(AUSSETZER) is not None
    assert B.pruefe_stand({"par1": 0, "par55": 0}) is None      # zu klein fuer ein Urteil


# ── Aenderungsverlauf ────────────────────────────────────────────────────

def _reihe():
    return [
        _s("a", "2026-10-19T20:00:00+00:00", ECHT, B.ANLASS_ERSTE),
        _s("b", "2026-10-19T23:43:54+00:00", AUSSETZER),                # 01:43 Ortszeit
        _s("c", "2026-10-19T23:58:54+00:00", ECHT),                     # 01:58 wieder da
        _s("d", "2026-10-20T16:02:19+00:00", {**ECHT, "par1": 0}),      # echte Aenderung
    ]


def test_verlauf_ueberspringt_aussetzer():
    verlauf = B.aenderungsverlauf(_reihe())
    assert len(verlauf) == 1
    assert verlauf[0]["time"] == "2026-10-20T16:02:19+00:00"
    assert [p["par"] for p in verlauf[0]["items"]] == ["par1"]


def test_verlauf_vergleicht_mit_letztem_gueltigen_stand():
    """Echte Änderung im Stand nach dem Aussetzer: gegen den Stand davor."""
    reihe = _reihe()
    reihe[2] = _s("c", "2026-10-19T23:58:54+00:00", {**ECHT, "par55": 48})
    verlauf = B.aenderungsverlauf(reihe)
    assert len(verlauf) == 2
    erste = verlauf[0]["items"]
    assert len(erste) == 1 and erste[0]["old"] == 50 and erste[0]["new"] == 48


def test_aussetzer_und_letzte_gueltige():
    reihe = _reihe()
    assert set(B.aussetzer(reihe)) == {"b"}
    assert B.letzte_gueltige(reihe).id == "d"
    assert B.letzte_gueltige(reihe[:2]).id == "a"


# ── Ablage ───────────────────────────────────────────────────────────────

def _ablage():
    ablage = ST.Sicherungsablage(None, "test", behalten=50)
    return ablage


def test_ablage_sichert_keinen_aussetzer():
    async def lauf():
        ablage = _ablage()
        await ablage.async_erstelle(ECHT, {}, grund="erste")
        _JETZT[0] += datetime.timedelta(minutes=15)
        s = await ablage.async_erstelle(AUSSETZER, {}, anlass=B.ANLASS_AUTOMATISCH)
        assert s is None
        assert len(ablage.alle) == 1
    asyncio.run(lauf())


def test_ablage_stellt_keinen_aussetzer_wieder_her():
    async def lauf():
        ablage = _ablage()
        await ablage.async_laden()
        # So liegt es in bestehenden Ablagen (gespeichert vor v4.0.1)
        ablage._sicherungen = sorted(_reihe(), key=lambda s: s.zeitpunkt, reverse=True)
        geschrieben = []

        async def schreiber(par, wert):
            geschrieben.append(par)
        try:
            await ablage.async_wiederherstellen("b", ECHT, schreiber, {}, probelauf=False)
        except ValueError as err:
            assert "Aussetzer" in str(err)
        else:
            raise AssertionError("Aussetzer haette abgelehnt werden muessen")
        assert not geschrieben
        assert ablage.neueste_gueltige.id == "d"
    asyncio.run(lauf())


# ── Konfigurations-Koordinator ───────────────────────────────────────────

class _Stammdaten:
    def als_dict(self):
        return {}


class _Api:
    def __init__(self, staende):
        self.staende = list(staende)
        self.stammdaten = _Stammdaten()

    async def async_lies_konfiguration(self):
        return dict(self.staende.pop(0))

    async def async_lies_stammdaten_kopf(self):
        return None


def test_koordinator_verwirft_aussetzer():
    """Kein Übernehmen, keine Sicherung, Abruf gilt als fehlgeschlagen."""
    async def lauf():
        ablage = _ablage()
        api = _Api([ECHT, AUSSETZER, {**ECHT, "par1": 0}])
        k = SC.ESHeatpumpSettingsCoordinator(None, api, ablage, 900, 24, "4.0.1")
        k.data = await k._async_update_data()
        assert len(ablage.alle) == 1                         # Erstaufnahme
        _JETZT[0] += datetime.timedelta(minutes=15)
        try:
            await k._async_update_data()
        except SC.UpdateFailed as err:
            assert "Softwareversion" in str(err)
        else:
            raise AssertionError("Aussetzer haette verworfen werden muessen")
        assert k.data == ECHT                                # vorheriger Stand bleibt
        assert len(ablage.alle) == 1                         # keine Sicherung
        _JETZT[0] += datetime.timedelta(minutes=15)
        k.data = await k._async_update_data()               # echte Aenderung
        assert len(ablage.alle) == 2
        assert ablage.neueste.label == "Änderung erkannt"
        assert "Anlage ein/aus" in ablage.neueste.grund
    asyncio.run(lauf())


def test_koordinator_ohne_daten_prueft_gegen_ablage():
    """Nach einem Neustart (noch kein self.data) gilt die letzte gültige Sicherung."""
    async def lauf():
        ablage = _ablage()
        await ablage.async_erstelle(ECHT, {}, grund="erste")
        k = SC.ESHeatpumpSettingsCoordinator(None, _Api([AUSSETZER]), ablage, 900, 24, "4.0.1")
        try:
            await k._async_update_data()
        except SC.UpdateFailed:
            pass
        else:
            raise AssertionError("Aussetzer haette verworfen werden muessen")
        assert len(ablage.alle) == 1
    asyncio.run(lauf())
