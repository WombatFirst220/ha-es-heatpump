"""Stammdaten der Anlage - Modell, Seriennummern, Garantie, Installateur.

Das Portal liefert diese Angaben in ``/a/amt/deviceList/listData`` gleich mit,
wenn die Integration ohnehin das Geraet sucht. Sie aendern sich praktisch nie,
kosten also keine zusaetzliche Abfrage - und sie sind genau das, was man beim
Garantiefall, bei einer Ersatzteilbestellung oder beim Ausfuellen eines
Serviceformulars sucht und dann nirgends findet.

Zwei Seriennummern
------------------
Das Feld ``note`` enthaelt beide::

    "AW12-R32-M-V8 IG: 230098-240115-0041 AG: 230101-240117-0042"

``IG`` ist das Innengeraet (Hydraulikmodul), ``AG`` das Aussengeraet. Das
separate Feld ``devicenum`` traegt nur eine der beiden - bei diesem Geraet die
des Aussengeraets. Wer ein Ersatzteil fuer das Innengeraet bestellt, braucht
die andere.

Das Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA testen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Beschriftungen im Kopf der Portal-Seite /a/amt/setdata/form.
# Dienen als Rueckfallweg, falls die Geraeteliste einmal weniger liefert.
_KOPF_FELDER = {
    "MAC": "mac",
    "Binding user": "besitzer",
    "Installer": "installateur",
    "Unit Model No.": "modell",
    "Unit Serial No.": "seriennummer",
    "Article No.": "artikelnummer",
    "Start-Up": "inbetriebnahme",
    "Warranty Period": "garantie_bis",
}

_SERIEN_RE = re.compile(r"\b(IG|AG)\s*:\s*([0-9A-Za-z-]+)")


@dataclass
class Stammdaten:
    """Alles, was sich ueber die Anlage sagen laesst, ohne sie zu befragen."""

    modell: str | None = None
    seriennummer: str | None = None
    seriennummer_innengeraet: str | None = None
    seriennummer_aussengeraet: str | None = None
    artikelnummer: str | None = None
    mac: str | None = None
    mn: str | None = None
    devid: str | None = None
    inbetriebnahme: str | None = None
    garantie_bis: str | None = None
    installateur: str | None = None
    installateur_kuerzel: str | None = None
    besitzer: str | None = None
    standort: str | None = None
    zeitzone: str | None = None
    angelegt_am: str | None = None
    zuletzt_geaendert: str | None = None
    rohdaten: dict[str, Any] = field(default_factory=dict)

    def als_dict(self) -> dict[str, Any]:
        """Flache Darstellung ohne Rohdaten - fuer Attribute und Sicherungen."""
        return {
            k: v
            for k, v in self.__dict__.items()
            if k != "rohdaten" and v not in (None, "")
        }

    @property
    def garantie_restjahre(self) -> float | None:
        """Jahre bis zum Garantieende, negativ wenn abgelaufen."""
        import datetime

        if not self.garantie_bis:
            return None
        try:
            ende = datetime.date.fromisoformat(self.garantie_bis[:10])
        except ValueError:
            return None
        return round((ende - datetime.date.today()).days / 365.25, 2)


def _text(wert: Any) -> str | None:
    if wert is None:
        return None
    s = str(wert).strip()
    return s or None


def aus_geraeteliste(eintrag: dict[str, Any]) -> Stammdaten:
    """Baut die Stammdaten aus einem Eintrag von ``/a/amt/deviceList/listData``.

    Alle Felder sind optional - ein Portal-Umbau darf hoechstens Luecken
    hinterlassen, niemals die Integration anhalten.
    """
    s = Stammdaten(rohdaten={k: v for k, v in eintrag.items()
                             if isinstance(v, (str, int, float, bool))})

    s.modell = _text(eintrag.get("devicetype"))
    s.seriennummer = _text(eintrag.get("devicenum"))
    s.mac = _text(eintrag.get("mac"))
    s.mn = _text(eintrag.get("mn"))
    s.devid = _text(eintrag.get("devid"))
    s.inbetriebnahme = _text(eintrag.get("firstruntime"))
    s.garantie_bis = _text(eintrag.get("warrantyperiod"))
    s.standort = _text(eintrag.get("address"))
    s.zeitzone = _text(eintrag.get("timezone"))
    s.angelegt_am = _text(eintrag.get("createDate"))
    s.zuletzt_geaendert = _text(eintrag.get("updateDate"))

    # Beide Seriennummern stecken im Freitextfeld "note"
    for kennung, nummer in _SERIEN_RE.findall(str(eintrag.get("note") or "")):
        if kennung == "IG":
            s.seriennummer_innengeraet = nummer
        else:
            s.seriennummer_aussengeraet = nummer

    # Installateur und Besitzer sind verschachtelt
    buero = eintrag.get("office")
    if isinstance(buero, dict):
        s.installateur = _text(buero.get("officeName"))
        s.installateur_kuerzel = _text(buero.get("officeCode"))
    benutzer = eintrag.get("user") or eintrag.get("employee")
    if isinstance(benutzer, dict):
        s.besitzer = _text(
            benutzer.get("userName")
            or benutzer.get("empName")
            or benutzer.get("name")
        )

    return s


def aus_formularkopf(html_text: str, vorhandene: Stammdaten | None = None) -> Stammdaten:
    """Ergaenzt die Stammdaten um den Kopf von ``/a/amt/setdata/form``.

    Dort stehen zwei Angaben, die die Geraeteliste nicht fuehrt: der Name des
    Installateurs in Klartext und die Artikelnummer. Der Kopf ist eine einzige
    Textzeile, Beschriftung und Wert durch das volle Doppelpunktzeichen "："
    getrennt und die Paare durch geschuetzte Leerzeichen.
    """
    s = vorhandene or Stammdaten()

    treffer = re.search(
        r'<div class="box-content mb10">(.*?)</div>', html_text, re.S
    )
    if not treffer:
        return s

    roh = re.sub(r"<[^>]+>", " ", treffer.group(1))
    roh = roh.replace("&nbsp;", " ")
    # Paare "Beschriftung：Wert" trennen. Der Wert reicht bis zur naechsten
    # bekannten Beschriftung - ein Wert darf also Leerzeichen enthalten
    # ("2024-01-17 00:00").
    namen = "|".join(re.escape(k) for k in _KOPF_FELDER)
    for m in re.finditer(rf"({namen})\s*[：:]\s*(.*?)(?=\s+(?:{namen})\s*[：:]|$)", roh, re.S):
        feld = _KOPF_FELDER[m.group(1)]
        wert = _text(m.group(2))
        if wert and getattr(s, feld, None) in (None, ""):
            setattr(s, feld, wert)
    return s
