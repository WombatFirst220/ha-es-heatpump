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
# Plausibilitaet eines Standes (Portal-Aussetzer)
# ─────────────────────────────────────────────────────────────────────────
#
# Das Portal liefert gelegentlich einen setdata-Stand, in dem fast alle Werte 0
# sind (beobachtet am 20.10.2026 01:43: Softwareversion 218 -> 0,
# Datenbankversion 115 -> 0 und 56 weitere Einstellungen auf 0, eine
# Viertelstunde spaeter wieder alles wie vorher). Die Anlage hat dabei nichts
# verstellt - es ist ein Lesefehler. Wird so ein Stand gesichert, entstehen
# zwei "Aenderungen" mit je 58 Posten, und eine Wiederherstellung aus dieser
# Sicherung wuerde die Anlage tatsaechlich auf 0 setzen.

# Systeminformationen, die eine laufende Anlage nie auf 0 stellt: Software-
# und Datenbankversion der Bedieneinheit. Faellt eine davon von einem Wert
# auf 0, war es das Portal.
SYSTEMFELDER = ("par2", "par3")

# Gleichzeitig auf 0 springende Katalogwerte: Ein echter Eingriff aendert
# einige wenige Werte, eine Wiederherstellung bis zu 70 - aber auf ihre
# frueheren Werte, nicht alle auf 0, und ein Werksreset setzt Werkswerte.
# Ab 10 Werten, die vorher ungleich 0 waren, und mindestens der Haelfte davon
# gilt der Stand als Aussetzer. 10 schuetzt kleine Staende (Tests, kuenftig
# kleinere Kataloge) vor Fehlalarm; die Haelfte liegt weit ueber jedem
# denkbaren Bedieneingriff und weit unter dem beobachteten Aussetzer (100 %).
NULLSPRUNG_MIN = 10
NULLSPRUNG_ANTEIL = 0.5


def pruefe_stand(
    neu: dict[str, Any], vorher: dict[str, Any] | None = None
) -> str | None:
    """Erkennt einen unbrauchbaren Konfigurationsstand (Portal-Aussetzer).

    Rueckgabe: ``None``, wenn der Stand plausibel ist, sonst der Grund als
    Text (fuer Log und Fehlermeldung).

    Regeln (``vorher`` ist der letzte gueltige Stand, falls bekannt):

    1. Ein Systemfeld (``SYSTEMFELDER``) war vorher ungleich 0 und ist jetzt 0
       oder fehlt.
    2. Von den Katalogwerten, die vorher ungleich 0 waren, stehen jetzt
       mindestens ``NULLSPRUNG_ANTEIL`` (und mindestens ``NULLSPRUNG_MIN``)
       auf 0.
    3. Ohne Vorstand: Alle Katalogwerte sind 0 (mindestens
       ``NULLSPRUNG_MIN`` vorhanden) - so sieht keine laufende Anlage aus.
    """
    # Ein leerer Stand wird schon beim Abruf abgelehnt (keine parXX-Felder)
    # und nie gesichert; hier zaehlt nur, was ein Aussetzer sein kann.
    neu_z = {k: _zahl(v) for k, v in neu.items()}
    if vorher:
        alt_z = {k: _zahl(v) for k, v in vorher.items()}
        for par in SYSTEMFELDER:
            a, b = alt_z.get(par), neu_z.get(par)
            if isinstance(a, (int, float)) and a != 0 and (b is None or b == 0):
                name = SETTINGS[par].name if par in SETTINGS else par
                return f"{name} ({par}) {a} → {b if b is not None else 'fehlt'}"
        vorher_gesetzt = [
            p for p in SETTINGS
            if isinstance(alt_z.get(p), (int, float)) and alt_z.get(p) != 0 and p in neu_z
        ]
        auf_null = [p for p in vorher_gesetzt if neu_z.get(p) == 0]
        if (
            len(auf_null) >= NULLSPRUNG_MIN
            and len(auf_null) >= NULLSPRUNG_ANTEIL * len(vorher_gesetzt)
        ):
            return (
                f"{len(auf_null)} von {len(vorher_gesetzt)} gesetzten "
                "Einstellungen gleichzeitig auf 0"
            )
        return None
    katalog = [neu_z[p] for p in SETTINGS if p in neu_z]
    if len(katalog) >= NULLSPRUNG_MIN and all(v == 0 for v in katalog):
        return f"alle {len(katalog)} Einstellungen sind 0"
    return None


def aussetzer(sicherungen: Iterable["Sicherung"]) -> dict[str, str]:
    """Gespeicherte Portal-Aussetzer: Kennung -> Grund.

    Jeder Stand wird gegen den davor liegenden *gueltigen* geprueft - ein
    Aussetzer darf nicht zum Massstab fuer den naechsten werden.
    """
    ergebnis: dict[str, str] = {}
    letzte: Sicherung | None = None
    for s in sorted(sicherungen, key=_zeit_sortierung):
        fehler = pruefe_stand(s.pars, letzte.pars if letzte else None)
        if fehler is None:
            letzte = s
        else:
            ergebnis[s.id] = fehler
    return ergebnis


def letzte_gueltige(sicherungen: Iterable["Sicherung"]) -> "Sicherung | None":
    """Juengste Sicherung, die kein Portal-Aussetzer ist."""
    liste = list(sicherungen)
    schlecht = aussetzer(liste)
    gueltig = [s for s in liste if s.id not in schlecht]
    return max(gueltig, key=_zeit_sortierung) if gueltig else None


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


def _wert_lesbar(par: str, wert: Any) -> str:
    """Nur der Wert, ohne den Namen davor ("38 °C", "Ein", "Eco")."""
    if wert is None:
        return "-"
    try:
        return beschreibe(par, wert).split(": ", 1)[-1]
    except (TypeError, ValueError):
        return str(wert)


def _als_utc(zeitpunkt: str) -> datetime.datetime | None:
    try:
        zeit = datetime.datetime.fromisoformat(str(zeitpunkt))
    except ValueError:
        return None
    if zeit.tzinfo is None:
        # Aeltere Staende ohne Zone: als UTC lesen statt zu raten
        zeit = zeit.replace(tzinfo=datetime.timezone.utc)
    return zeit.astimezone(datetime.timezone.utc)


def _zeit_utc(zeitpunkt: str) -> str:
    """ISO-8601-Zeitpunkt in UTC; unlesbare Angaben bleiben unveraendert."""
    zeit = _als_utc(zeitpunkt)
    return zeit.isoformat() if zeit is not None else str(zeitpunkt)


def _zeit_sortierung(s: "Sicherung") -> tuple[int, Any]:
    zeit = _als_utc(s.zeitpunkt)
    return (0, zeit) if zeit is not None else (1, str(s.zeitpunkt))


def aenderungsverlauf(
    sicherungen: Iterable[Sicherung], nur_bekannte: bool = True
) -> list[dict[str, Any]]:
    """Einstellungsaenderungen aus aufeinanderfolgenden Sicherungen.

    Grundlage der Auswertungsseite: Sie markiert, wann sich etwas an der
    Konfiguration geaendert hat, damit sich Verbrauch und Arbeitszahl davor und
    danach vergleichen lassen.

    Je Paar benachbarter Staende (aelteste zuerst) entsteht ein Eintrag mit dem
    Zeitpunkt und Anlass der *juengeren* Sicherung - dort ist die Aenderung
    erstmals zu sehen. Paare ohne Abweichung fallen weg.

    Gespeicherte Portal-Aussetzer (siehe ``pruefe_stand``) werden
    uebersprungen; der naechste Stand wird dann mit dem letzten *gueltigen*
    verglichen. So verschwinden Paare wie "alles auf 0" / "alles zurueck".

    ``nur_bekannte``: Die rund 230 Felder ohne Katalogeintrag sind ueberwiegend
    Messwerte und Zaehlerstaende, die sich zwischen zwei Sicherungen praktisch
    immer aendern. Sie mitzuzaehlen, machte aus jeder Sicherung eine
    "Aenderung". Deshalb standardmaessig nur Werte aus ``SETTINGS``.
    """
    reihe = sorted(sicherungen, key=_zeit_sortierung)
    ergebnis: list[dict[str, Any]] = []
    alt: Sicherung | None = None
    for neu in reihe:
        if pruefe_stand(neu.pars, alt.pars if alt else None) is not None:
            continue
        if alt is None:
            alt = neu
            continue
        if alt.pruefsumme and alt.pruefsumme == neu.pruefsumme:
            alt = neu
            continue
        posten = []
        for a in vergleiche(alt.pars, neu.pars):
            if nur_bekannte and not a.bekannt:
                continue
            vorher, nachher = _wert_lesbar(a.par, a.vorher), _wert_lesbar(a.par, a.nachher)
            posten.append({
                "par": a.par,
                "name": a.name,
                "group": a.gruppe,
                "old": a.vorher,
                "new": a.nachher,
                "text": f"{a.gruppe} / {a.name}: {vorher} → {nachher}",
            })
        if posten:
            ergebnis.append({
                "time": _zeit_utc(neu.zeitpunkt),
                "reason": neu.anlass,
                "items": posten,
            })
        alt = neu
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
