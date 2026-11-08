"""Auswertung von Portal-Antworten - ohne Home Assistant testbar.

Hier steht nur Logik, die aus einer Antwort von myheatpump.com eine
Entscheidung ableitet: Ist das eine gueltige Messwert-Antwort? Ist die Sitzung
abgelaufen? Hat das Portal die Anmeldung eindeutig abgelehnt?

Warum eigenes Modul (v4.0.1): Die Unterscheidung "abgelaufene Sitzung" gegen
"falsches Passwort" gegen "Portal hat gerade Wartung" entscheidet darueber, ob
die Integration sich selbst heilt, still weiterlaeuft oder den Benutzer um ein
neues Passwort bittet. Das soll sich ohne laufendes Home Assistant pruefen
lassen.
"""
from __future__ import annotations

import json
import re
from typing import Any

PAR_MUSTER = re.compile(r"^par\d+$")

# Ergebnis von login_einordnen()
LOGIN_OK = "ok"
LOGIN_ABGELEHNT = "abgelehnt"   # falsches Passwort / unbekanntes Konto -> Reauth
LOGIN_UNKLAR = "unklar"         # Wartung, Captcha, unbekannte Antwort -> erneut versuchen

# Hinweise auf eine voruebergehende Stoerung. Sie haben Vorrang vor den
# Ablehnungswoertern: "Wartung, bitte Passwort spaeter erneut eingeben" ist
# kein falsches Passwort.
_VORUEBERGEHEND = (
    "maintenance", "wartung", "维护", "busy", "try again", "later", "spaeter",
    "später", "timeout", "超时", "captcha", "verification code", "validcode",
    "验证码", "too many", "频繁", "server error", "系统",
)

# Eindeutige Ablehnung der Zugangsdaten (jeesite liefert je nach Portal
# englische oder chinesische Meldungen).
_ABGELEHNT = (
    "password", "passwort", "kennwort", "密码", "账号", "帐号", "用户名",
    "username", "user name", "account", "konto", "benutzer", "incorrect",
    "wrong", "falsch", "not exist", "does not exist", "不存在", "错误",
    "locked", "gesperrt", "disabled", "冻结", "停用",
)


def login_einordnen(antwort: Any) -> str:
    """Ordnet die JSON-Antwort von /a/login ein.

    Bestaetigte Erfolgsantwort: ``{"msg": "Login successful!"}``; ausserdem
    ``{"success": true}``, ``{"code": 0}`` oder ``{"code": 200}``.

    Nur eine *eindeutige* Ablehnung der Zugangsdaten zaehlt als
    ``LOGIN_ABGELEHNT``. Bis v4.0.0 galt jede Antwort ohne "success" als
    falsches Passwort - eine Wartungsseite hat die Integration dann dauerhaft
    lahmgelegt, obwohl ein spaeterer Versuch genuegt haette.
    """
    if not isinstance(antwort, dict):
        return LOGIN_UNKLAR
    meldung = str(antwort.get("msg") or antwort.get("message") or "").lower()
    if (
        antwort.get("success") is True
        or antwort.get("code") in (0, 200, "0", "200")
        or ("success" in meldung and "unsuccess" not in meldung)
    ):
        return LOGIN_OK
    if any(w in meldung for w in _VORUEBERGEHEND):
        return LOGIN_UNKLAR
    if any(w in meldung for w in _ABGELEHNT):
        return LOGIN_ABGELEHNT
    if antwort.get("code") in (401, 403, "401", "403"):
        return LOGIN_ABGELEHNT
    return LOGIN_UNKLAR


class SitzungAbgelaufen(Exception):
    """Das Portal hat nicht mit Daten geantwortet, sondern mit der Anmeldeseite.

    jeesite leitet eine abgelaufene Sitzung auf die Login-Seite um (HTML) oder
    antwortet mit einer JSON-Meldung ohne Nutzdaten. Beides heisst: neu
    anmelden und den Abruf wiederholen.
    """


class UnerwarteteAntwort(Exception):
    """Gueltiges JSON, aber in einer Form, mit der nichts anzufangen ist."""


def antwort_auswerten(
    text: str,
    content_type: str | None = None,
    *,
    erwarte_parameter: bool = True,
) -> dict[str, Any]:
    """Prueft eine Portal-Antwort und liefert das JSON-Objekt.

    Wirft ``SitzungAbgelaufen``, wenn die Antwort nach Anmeldeseite aussieht:
    HTML, kein JSON, ein Sitzungsfehler-Code oder - bei ``erwarte_parameter``
    (realdata, setdata/get) - ein Objekt ohne ein einziges ``parXX``.

    Wirft ``UnerwarteteAntwort``, wenn gueltiges JSON keine Objekt-Form hat
    (z. B. eine Liste); das ist kein Sitzungsproblem und wird durch erneutes
    Anmelden nicht besser.
    """
    roh = (text or "").lstrip()
    if "html" in (content_type or "").lower() or roh.startswith("<"):
        raise SitzungAbgelaufen("HTML statt JSON (Weiterleitung zur Anmeldeseite)")
    try:
        daten = json.loads(roh)
    except ValueError as err:
        raise SitzungAbgelaufen(f"Antwort ist kein JSON ({err})") from err
    if not isinstance(daten, dict):
        raise UnerwarteteAntwort(
            f"Antwort ist ein {type(daten).__name__}, erwartet war ein Objekt"
        )
    if daten.get("code") in (401, 403, "401", "403"):
        raise SitzungAbgelaufen(f"Portal meldet Code {daten.get('code')}")
    if erwarte_parameter and not any(PAR_MUSTER.match(str(k)) for k in daten):
        raise SitzungAbgelaufen(
            "Antwort ohne parXX-Felder, Schluessel: "
            f"{list(daten.keys())[:10]}"
        )
    return daten
