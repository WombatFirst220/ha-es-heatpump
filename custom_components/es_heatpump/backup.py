"""Versionierte Sicherungen der Anlagenkonfiguration - die reine Logik.

Warum das noetig ist
--------------------
Die Bedieneinheit der Waermepumpe kennt kein Zurueck. Wer eine Heizkurve
verstellt, einen Legionellenschutz abschaltet oder waehrend einer Fehlersuche
zehn Werte anfasst, hat hinterher keine Moeglichkeit, den vorherigen Stand
wiederherzustellen - ausser aus dem Gedaechtnis. Ein Servicetechniker, der
"mal eben etwas probiert", hinterlaesst denselben Zustand.

Dieses Modul haelt den vollstaendigen Satz von 300 Konfigurationswerten als
Zeitreihe vor. Jede Sicherung ist ein vollstaendiger Stand, kein Delta -
Deltas sind kleiner, aber eine beschaedigte Kette macht alle folgenden
unbrauchbar, und 300 Zahlen sind nicht gross.

Dieses Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA
testen. Die Ablage uebernimmt ``backup_store.py``.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .settings import SETTINGS, beschreibe

# Warum eine Sicherung angelegt wurde
ANLASS_MANUELL = "manuell"
ANLASS_AUTOMATISCH = "automatisch"
ANLASS_VOR_SCHREIBEN = "vor-schreibzugriff"
ANLASS_VOR_WIEDERHERSTELLUNG = "vor-wiederherstellung"
ANLASS_ERSTE = "erstaufnahme"

# Diese Anlaesse werden beim Aufraeumen nie geloescht: sie dokumentieren einen
# Eingriff, und genau danach sucht man spaeter.
GESCHUETZTE_ANLAESSE = frozenset(
    {ANLASS_ERSTE, ANLASS_VOR_SCHREIBEN, ANLASS_VOR_WIEDERHERSTELLUNG}
)


@dataclass
class Sicherung:
    """Ein vollstaendiger Konfigurationsstand zu einem Zeitpunkt."""

    id: str
    zeitpunkt: str                       # ISO 8601, mit Zeitzone
    anlass: str
    label: str = ""
    grund: str = ""
    pars: dict[str, float] = field(default_factory=dict)
    stammdaten: dict[str, Any] = field(default_factory=dict)
    version: str = ""                    # Version der Integration
    pruefsumme: str = ""

    def __post_init__(self) -> None:
        if not self.pruefsumme:
            self.pruefsumme = pruefsumme_von(self.pars)

    # -- Darstellung ---------------------------------------------------
    @property
    def anzahl(self) -> int:
        return len(self.pars)

    def kurzfassung(self) -> dict[str, Any]:
        """Zeile fuer eine Uebersicht - ohne die 300 Werte."""
        return {
            "id": self.id,
            "zeitpunkt": self.zeitpunkt,
            "anlass": self.anlass,
            "label": self.label,
            "grund": self.grund,
            "anzahl_werte": self.anzahl,
            "pruefsumme": self.pruefsumme,
            "version": self.version,
        }

    def lesbar(self) -> dict[str, str]:
        """Alle *benannten* Werte im Klartext, nach Gruppe sortiert.

        Die 226 Felder ohne Katalogeintrag bleiben aussen vor - sie werden
        gesichert und wiederhergestellt, aber sie anzuzeigen hiesse, 226
        Zeilen "par203 = 0" zu produzieren.
        """
        ergebnis: dict[str, str] = {}
        for par, wert in self.pars.items():
            s = SETTINGS.get(par)
            if s is None:
                continue
            ergebnis[f"{s.group} / {s.name}"] = beschreibe(par, wert).split(": ", 1)[-1]
        return dict(sorted(ergebnis.items()))

    def als_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1, sort_keys=True)


def pruefsumme_von(pars: dict[str, Any]) -> str:
    """Stabiler Fingerabdruck eines Konfigurationsstandes.

    Damit laesst sich in einem Schritt feststellen, ob sich seit der letzten
    Sicherung ueberhaupt etwas geaendert hat - ohne 300 Werte zu vergleichen
    und ohne dass die Reihenfolge der Schluessel eine Rolle spielt.
    """
    roh = json.dumps(
        {k: _zahl(v) for k, v in sorted(pars.items())},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


def _zahl(wert: Any) -> float | Any:
    try:
        f = float(wert)
    except (TypeError, ValueError):
        return wert
    return int(f) if f.is_integer() else f


def neue_id(zeitpunkt: datetime.datetime) -> str:
    """Zeitbasierte, sortierbare und menschenlesbare Kennung."""
    return zeitpunkt.strftime("%Y%m%d-%H%M%S")


# ─────────────────────────────────────────────────────────────────────────
# Vergleich
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Abweichung:
    """Ein Wert, der sich zwischen zwei Staenden unterscheidet."""

    par: str
    vorher: Any
    nachher: Any
    name: str
    gruppe: str
    schreibbar: bool
    bekannt: bool

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vorher_lesbar"] = beschreibe(self.par, self.vorher) if self.bekannt else str(self.vorher)
        d["nachher_lesbar"] = beschreibe(self.par, self.nachher) if self.bekannt else str(self.nachher)
        return d


def vergleiche(alt: dict[str, Any], neu: dict[str, Any]) -> list[Abweichung]:
    """Alle Unterschiede zwischen zwei Konfigurationsstaenden.

    Felder, die nur in einem der beiden Staende vorkommen, gelten als
    Abweichung mit ``None`` auf der fehlenden Seite - ein Portal-Umbau, der
    Felder hinzufuegt oder entfernt, soll sichtbar werden und nicht
    stillschweigend verschwinden.
    """
    ergebnis: list[Abweichung] = []
    for par in sorted(set(alt) | set(neu), key=_par_sortierung):
        a, b = _zahl(alt.get(par)), _zahl(neu.get(par))
        if a == b:
            continue
        s = SETTINGS.get(par)
        ergebnis.append(
            Abweichung(
                par=par,
                vorher=a,
                nachher=b,
                name=s.name if s else f"Unbenanntes Feld {par}",
                gruppe=s.group if s else "Ohne Katalogeintrag",
                schreibbar=bool(s and s.writable),
                bekannt=s is not None,
            )
        )
    return ergebnis


def _par_sortierung(par: str) -> tuple[int, str]:
    try:
        return (int(par[3:]), "")
    except (ValueError, IndexError):
        return (10**6, par)


# ─────────────────────────────────────────────────────────────────────────
# Aufraeumen
# ─────────────────────────────────────────────────────────────────────────

def aufraeumen(
    sicherungen: list[Sicherung], behalten: int
) -> tuple[list[Sicherung], list[Sicherung]]:
    """Teilt die Liste in (bleiben, werden geloescht).

    Regeln, in dieser Reihenfolge:

    1. Sicherungen mit geschuetztem Anlass bleiben **immer**. Wer eine
       Wiederherstellung sucht, sucht den Stand *davor* - und der ist oft
       aelter als jedes Aufbewahrungsfenster.
    2. Von den uebrigen bleiben die ``behalten`` juengsten.

    ``behalten <= 0`` schaltet das Aufraeumen ab.
    """
    if behalten <= 0:
        return list(sicherungen), []

    nach_zeit = sorted(sicherungen, key=lambda s: s.zeitpunkt, reverse=True)
    bleiben: list[Sicherung] = []
    weg: list[Sicherung] = []
    frei = behalten
    for s in nach_zeit:
        if s.anlass in GESCHUETZTE_ANLAESSE:
            bleiben.append(s)
        elif frei > 0:
            bleiben.append(s)
            frei -= 1
        else:
            weg.append(s)
    bleiben.sort(key=lambda s: s.zeitpunkt, reverse=True)
    return bleiben, weg


# ─────────────────────────────────────────────────────────────────────────
# Wiederherstellung planen
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Wiederherstellungsplan:
    """Was eine Wiederherstellung tun wuerde - und was sie auslassen muss."""

    zu_schreiben: list[Abweichung] = field(default_factory=list)
    uebersprungen: list[Abweichung] = field(default_factory=list)

    @property
    def anzahl(self) -> int:
        return len(self.zu_schreiben)

    def als_dict(self) -> dict[str, Any]:
        return {
            "zu_schreiben": [a.als_dict() for a in self.zu_schreiben],
            "uebersprungen": [
                {**a.als_dict(), "warum": _warum_uebersprungen(a)}
                for a in self.uebersprungen
            ],
            "anzahl_schreibvorgaenge": self.anzahl,
        }


def _warum_uebersprungen(a: Abweichung) -> str:
    if not a.bekannt:
        return ("Das Portal bietet dieses Feld nicht zum Bearbeiten an - es wird "
                "gesichert, laesst sich aber nicht zurueckschreiben.")
    if not a.schreibbar:
        return "Nur-Lese-Wert (Firmware-Version o. Ae.)."
    if a.nachher is None:
        return "Im Zielstand nicht enthalten."
    return "Unbekannter Grund."


def plane_wiederherstellung(
    jetzt: dict[str, Any], ziel: dict[str, Any]
) -> Wiederherstellungsplan:
    """Ermittelt die Schreibvorgaenge, die ``jetzt`` auf ``ziel`` bringen.

    Wiederhergestellt wird **nur**, was das Portal auch zum Bearbeiten
    anbietet. Von den 300 gesicherten Feldern sind das 70. Die uebrigen 230
    sind Messwerte, Zaehlerstaende und Werkseinstellungen, die es entweder
    nicht anzunehmen gibt oder die man nicht anfassen will - sie werden
    gesichert, damit man *sieht*, wie sie waren, nicht damit man sie setzt.

    Der Plan wird immer erst gebaut und dann ausgefuehrt: So kann die
    Trockenuebung dasselbe Ergebnis zeigen, das der Ernstfall schreiben wird.
    """
    plan = Wiederherstellungsplan()
    for a in vergleiche(jetzt, ziel):
        eintrag = SETTINGS.get(a.par)
        if eintrag is None or not eintrag.writable or a.nachher is None:
            plan.uebersprungen.append(a)
            continue
        try:
            eintrag.validate(a.nachher)
        except ValueError:
            plan.uebersprungen.append(a)
            continue
        plan.zu_schreiben.append(a)
    return plan


def aus_dict(roh: dict[str, Any]) -> Sicherung:
    """Liest eine Sicherung aus der Ablage zurueck, tolerant gegen Zusatzfelder."""
    erlaubt = {
        "id", "zeitpunkt", "anlass", "label", "grund",
        "pars", "stammdaten", "version", "pruefsumme",
    }
    return Sicherung(**{k: v for k, v in roh.items() if k in erlaubt})


def als_liste(sicherungen: Iterable[Sicherung]) -> list[dict[str, Any]]:
    return [asdict(s) for s in sicherungen]
