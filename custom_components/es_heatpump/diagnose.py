"""Schwaerzung der Diagnosedaten (v4.1.0) - die reine Logik.

Die Diagnose-Datei ("Diagnosedaten herunterladen") landet erfahrungsgemaess in
GitHub-Issues und Foren. Sie darf deshalb nichts enthalten, womit sich jemand
am Portal anmelden, die Anlage einer Person zuordnen oder das Geraet im Portal
ansprechen koennte:

* Zugangsdaten: ``password``, ``username``, Sitzungs-Cookies (``JSESSIONID``)
* Personenbezug: ``besitzer``, ``standort``, ``installateur`` (samt Kuerzel),
  E-Mail-Adressen in beliebigen Texten - der Benutzername IST meist eine
* Geraetekennungen: ``mac``, ``seriennummer*`` (Innen-/Aussengeraet),
  ``artikelnummer``, ``mn``/``devid`` (damit adressiert das Portal die Anlage),
  ``portal_kennung``

Die Schluessel-Pruefung ist bewusst grosszuegig (Gross-/Kleinschreibung egal,
Praefixe fuer Seriennummer und Installateur): Lieber ein Wert zu viel
geschwaerzt als eine Seriennummer im Issue-Tracker.

``diagnostics.py`` reicht die hier ermittelten Schluessel an
``async_redact_data`` von Home Assistant weiter und schwaerzt danach noch
E-Mail-Adressen und den Benutzernamen in Texten (Titel, unique_ids, Gruende).
Das Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA testen.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# Gleicher Platzhalter wie homeassistant.components.diagnostics.REDACTED
GESCHWAERZT = "**REDACTED**"

# Exakte Schluessel (klein geschrieben verglichen)
SCHWAERZEN: frozenset[str] = frozenset({
    "password",
    "username",
    "mac",
    "artikelnummer",
    "besitzer",
    "standort",
    "installateur",
    "mn",
    "devid",
    "portal_kennung",
    "jsessionid",
    "cookie",
    "cookies",
    "set-cookie",
    "email",
    "e-mail",
})

# Praefixe: seriennummer, seriennummer_innengeraet, seriennummer_aussengeraet,
# installateur_kuerzel ...
SCHWAERZEN_PRAEFIXE: tuple[str, ...] = ("seriennummer", "installateur", "jsessionid")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def ist_zu_schwaerzen(schluessel: Any) -> bool:
    """True, wenn der Wert unter diesem Schluessel nicht in die Diagnose darf."""
    if not isinstance(schluessel, str):
        return False
    s = schluessel.strip().lower()
    return s in SCHWAERZEN or s.startswith(SCHWAERZEN_PRAEFIXE)


def zu_schwaerzende_schluessel(daten: Any) -> set[str]:
    """Alle Schluessel in ``daten`` (verschachtelt), die geschwaerzt werden.

    ``async_redact_data`` vergleicht exakt; deshalb werden hier die tatsaechlich
    vorkommenden Schreibweisen gesammelt (``JSESSIONID`` wie ``jsessionid``).
    """
    gefunden: set[str] = set()

    def _lauf(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if ist_zu_schwaerzen(k):
                    gefunden.add(k)
                _lauf(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _lauf(v)

    _lauf(daten)
    return gefunden


def schwaerze_texte(daten: Any, zusaetzlich: Iterable[str | None] = ()) -> Any:
    """Ersetzt E-Mail-Adressen und die Begriffe ``zusaetzlich`` in allen Texten.

    ``zusaetzlich`` ist typischerweise der Benutzername - er steckt auch in
    Titel ("ES Heatpump (<benutzer>)") und unique_ids, wo ihn keine
    Schluessel-Schwaerzung erreicht. Leere und sehr kurze Begriffe (< 3 Zeichen)
    werden ignoriert, sonst wuerde jedes "a" im Text ersetzt.
    """
    begriffe = sorted(
        {b for b in zusaetzlich if isinstance(b, str) and len(b) >= 3},
        key=len, reverse=True,
    )
    muster = (
        re.compile("|".join(re.escape(b) for b in begriffe), re.IGNORECASE)
        if begriffe else None
    )

    def _text(t: str) -> str:
        t = _EMAIL_RE.sub(GESCHWAERZT, t)
        if muster is not None:
            t = muster.sub(GESCHWAERZT, t)
        return t

    def _lauf(obj: Any) -> Any:
        if isinstance(obj, str):
            return _text(obj)
        if isinstance(obj, dict):
            return {
                (_text(k) if isinstance(k, str) else k): _lauf(v)
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple)):
            return [_lauf(v) for v in obj]
        return obj

    return _lauf(daten)


def schwaerze_schluessel(daten: Any, schluessel: Iterable[str] | None = None) -> Any:
    """HA-freies Gegenstueck zu ``async_redact_data`` (fuer Tests und Rueckfall).

    Ohne ``schluessel`` gilt die Regel aus ``ist_zu_schwaerzen``. Leere Werte
    (None, "") bleiben stehen - so sieht man, dass ein Feld leer *war*.
    """
    menge = set(schluessel) if schluessel is not None else None

    def _treffer(k: Any) -> bool:
        return (k in menge) if menge is not None else ist_zu_schwaerzen(k)

    def _lauf(obj: Any) -> Any:
        if isinstance(obj, dict):
            aus = {}
            for k, v in obj.items():
                if _treffer(k) and v not in (None, ""):
                    aus[k] = GESCHWAERZT
                else:
                    aus[k] = _lauf(v)
            return aus
        if isinstance(obj, (list, tuple)):
            return [_lauf(v) for v in obj]
        return obj

    return _lauf(daten)


def schwaerze(daten: Any, zusaetzlich: Iterable[str | None] = ()) -> Any:
    """Vollstaendige Schwaerzung: Schluessel, dann Texte."""
    return schwaerze_texte(schwaerze_schluessel(daten), zusaetzlich)
