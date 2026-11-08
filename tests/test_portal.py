"""Tests für die Auswertung von Portal-Antworten (v4.0.1).

Ohne Home-Assistant-Abhängigkeit, siehe Kopf von tests/test_mode.py.
Geprüft wird die Unterscheidung, an der Selbstheilung und erneute Anmeldung
hängen: abgelaufene Sitzung, abgelehnte Zugangsdaten, vorübergehende Störung.
"""
import importlib.util
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_portal"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


P = _lade("portal")


# ── Sitzung abgelaufen ──────────────────────────────────────────────────────

def test_gueltige_messwerte():
    daten = P.antwort_auswerten('{"isNewRecord": true, "mn": 1, "par1": 2.0}', "application/json")
    assert daten["par1"] == 2.0


@pytest.mark.parametrize("text, content_type", [
    ("<!DOCTYPE html><html><body>Login</body></html>", "text/html;charset=UTF-8"),
    ("   <html>", ""),
    ('{"par1": 1}', "text/html"),          # Content-Type allein genuegt
    ("", "application/json"),               # leere Antwort
    ("Fehler", "text/plain"),               # kein JSON
    ('{"code": 401, "msg": "not logged in"}', "application/json"),
    ('{"code": "403"}', None),
    ('{"result": "login", "message": "未登录或登录超时"}', "application/json"),
])
def test_sitzung_abgelaufen(text, content_type):
    with pytest.raises(P.SitzungAbgelaufen):
        P.antwort_auswerten(text, content_type)


def test_schreibantwort_ohne_parameter_ist_gueltig():
    daten = P.antwort_auswerten(
        '{"result": "true", "message": "ok"}', "application/json",
        erwarte_parameter=False,
    )
    assert daten["result"] == "true"


def test_schreibantwort_html_ist_sitzungsfehler():
    with pytest.raises(P.SitzungAbgelaufen):
        P.antwort_auswerten("<html>", "text/html", erwarte_parameter=False)


@pytest.mark.parametrize("text", ['[{"par1": 1}]', '"text"', "42", "null"])
def test_unerwartete_form(text):
    with pytest.raises(P.UnerwarteteAntwort):
        P.antwort_auswerten(text, "application/json")


def test_unerwartete_form_ist_kein_sitzungsfehler():
    # Sonst wuerde eine Liste als Antwort endlos neu anmelden lassen
    assert not issubclass(P.UnerwarteteAntwort, P.SitzungAbgelaufen)


# ── Anmeldung einordnen ─────────────────────────────────────────────────────

@pytest.mark.parametrize("antwort", [
    {"msg": "Login successful!"},
    {"success": True},
    {"code": 0},
    {"code": "200"},
])
def test_login_ok(antwort):
    assert P.login_einordnen(antwort) == P.LOGIN_OK


@pytest.mark.parametrize("antwort", [
    {"result": "false", "message": "Incorrect username or password"},
    {"msg": "账号或密码错误"},
    {"message": "Account does not exist"},
    {"msg": "Benutzer gesperrt"},
    {"code": 401},
])
def test_login_abgelehnt(antwort):
    assert P.login_einordnen(antwort) == P.LOGIN_ABGELEHNT


@pytest.mark.parametrize("antwort", [
    {"msg": "System maintenance, please try again later"},
    {"msg": "Please enter the verification code"},
    {"message": "Wrong password, too many attempts - try again later"},
    {"result": "false"},
    {},
    [],
    None,
    "Login successful!",
])
def test_login_unklar(antwort):
    # Keine eindeutige Ablehnung -> kein Reauth, sondern spaeter erneut versuchen
    assert P.login_einordnen(antwort) == P.LOGIN_UNKLAR
