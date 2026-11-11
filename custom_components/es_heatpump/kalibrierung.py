"""Volumenstrom aus Warmwasser-Ladungen kalibrieren (v4.2.0).

Free of Home Assistant imports so the rules stay unit-testable — see
``tests/test_kalibrierung.py``.

Warum
-----
Die Waermepumpe misst ihren Volumenstrom nicht. Die thermische Leistung (und
damit COP, Guetegrad, Waermemengen) rechnet die Integration aus

    P_th = V̇ × ΔT × 1,163

mit einem eingestellten V̇. Die Faustformel ``V̇ = Q × 0,86 / ΔT`` aus der
Auslegung hilft nicht, sie braucht Q - genau die Groesse, die gesucht ist.

Der Warmwasserspeicher ist dagegen ein Waermemengenzaehler, den jede Anlage
schon hat: Waehrend einer Ladung fliesst die Waerme des WP-Kreises (bis auf
Verluste) in den Speicher. Also

    V_Speicher × ΔT_Speicher × 1,163  =  V̇ × 1,163 × ∫ (Vorlauf − Ruecklauf) dt
    ⇒  V̇ [m³/h] = V_Speicher [m³] × ΔT_Speicher [K] / ∫ΔT dt [K·h]

``ΔT_Speicher`` liefert der Fuehler Tw (par7, T5), ``∫ΔT dt`` die Portalwerte
par4/par5. Gerechnet wird je Ladung, gewertet der Median der letzten Ladungen.

Was eine Ladung unbrauchbar macht
---------------------------------
- Zapfen waehrend der Ladung: Waerme verlaesst den Speicher, V̇ faellt zu
  niedrig aus. Erkennbar nur, wenn Tw nach Beginn des Anstiegs wieder faellt;
  sonst faengt der Median es.
- Zapfen VOR dem Anstieg ist dagegen der Normalfall: Oft startet die Ladung,
  weil gerade geduscht wird, und Tw faellt in den ersten Minuten noch um
  mehrere Kelvin (gemessen bis 6 K). Auch der kalte Waermetauscher kuehlt die
  Fuehlerzone kurz ab. Startwert ist deshalb das Minimum von Tw bis zum Beginn
  des Anstiegs, nicht der Wert beim Umschalten.
- Luecken in den Portalwerten (HTTP 500 kommt vor): Ohne Messpunkte fehlt ein
  Stueck ∫ΔT, waehrend Tw weiter steigt - V̇ fiele zu HOCH aus. Verworfen.
- Abtauen waehrend der Ladung: Der Kreisprozess entzieht dem Wasser Waerme.
- Nach dem Verdichter-Stopp zeigen Vor- und Ruecklauf bis zu 12 K Differenz,
  obwohl kaum noch Wasser fliesst. Integriert wird deshalb nur, solange die
  Betriebsart "Brauchwasser" bei laufendem Verdichter gilt.
- Kurze Nachladungen: wenig Anstieg, die 0,1-K-Aufloesung von Tw und
  Fuehler-Offsets wiegen schwer. Erst ab ``MIN_ANSTIEG_K``.
- Heizstab im Speicher (TBH): erwaermt ohne Waermepumpe. Laeuft er waehrend
  der Ladung, faellt V̇ zu hoch aus - der Median faengt Einzelfaelle.

Tw haengt der Ladung nach (Schichtung, Fuehler in der Tauchhuelse). Nach dem
Ende der Ladung wird deshalb noch ``NACHLAUF_S`` lang das Maximum von Tw
gesucht.

Systematisch faellt V̇ etwas zu NIEDRIG aus: Die Waerme, die den Wasserinhalt
von Waermepumpe, Leitungen und Waermetauscher von Ruecklauf- auf Vorlauf-
niveau bringt, steckt in ∫ΔT, aber nicht im Speicher. Bei 20-30 l im Kreis und
200 l Speicher sind das grob 10-20 %. Der Wert ist eine Untergrenze.
"""
from __future__ import annotations

from statistics import median
from typing import Any

# Wasser: 1,163 Wh/(l·K) steht auf beiden Seiten und kuerzt sich heraus.

PAR_VORLAUF = "par4"
PAR_RUECKLAUF = "par5"
PAR_SPEICHER = "par7"     # Tw / T5 - Warmwasserspeicher
PAR_FREQUENZ = "par20"

BETRIEBSART_LADUNG = "Brauchwasser"   # nur reine Warmwasserbereitung

MIN_DAUER_S = 10 * 60
MIN_ANSTIEG_K = 5.0
MAX_LUECKE_S = 120.0      # bei 10-s-Abruf: 12 fehlende Werte
MAX_ABFALL_K = 1.0        # Tw faellt nach Beginn des Anstiegs → gezapft
ANSTIEG_BEGINNT_K = 0.5   # ab so viel ueber dem Minimum gilt der Anstieg als begonnen
NACHLAUF_S = 10 * 60
MIN_INTEGRAL_KH = 0.2
PLAUSIBEL_M3H = (0.2, 10.0)

ANZAHL_LADUNGEN = 10      # Median ueber so viele gueltige Ladungen
MIN_LADUNGEN = 3          # vorher kein Wert

TEMP_SENTINEL = -99.0

# Modi der Option "flow_calibration"
KALIBRIERUNG_AUS = "aus"
KALIBRIERUNG_WARMWASSER = "warmwasser"
KALIBRIERUNG_BEIDE = "beide"
KALIBRIERUNG_OPTIONEN = [KALIBRIERUNG_AUS, KALIBRIERUNG_WARMWASSER, KALIBRIERUNG_BEIDE]


def _zahl(roh: Any) -> float | None:
    try:
        wert = float(roh)
    except (TypeError, ValueError):
        return None
    if wert == TEMP_SENTINEL:
        return None
    return wert


class _Ladung:
    """Eine laufende Warmwasser-Ladung."""

    def __init__(self, t: float, tw: float, spreizung: float) -> None:
        self.t_start = t
        self.t_ende: float | None = None
        self.tw_start = tw      # Minimum bis zum Beginn des Anstiegs
        self.tw_max = tw
        self.steigt = False
        self.integral_ks = 0.0          # K·s
        self.t_letzt = t
        self.spreizung_letzt = spreizung
        self.fehler: str | None = None

    def punkt(self, t: float, tw: float | None, spreizung: float | None) -> None:
        if self.fehler:
            return
        if tw is None or spreizung is None:
            self.fehler = "Messwert fehlt"
            return
        dt = t - self.t_letzt
        if dt > MAX_LUECKE_S:
            self.fehler = f"Datenluecke {dt:.0f} s"
            return
        if dt > 0:
            # Trapez: Portalwerte sind Stichproben eines stetigen Verlaufs
            self.integral_ks += dt * (max(0.0, spreizung) + max(0.0, self.spreizung_letzt)) / 2
        self.t_letzt = t
        self.spreizung_letzt = spreizung
        if not self.steigt:
            # Vor dem Anstieg zaehlt nur das Minimum; das Maximum laeuft mit,
            # sonst saehe der Beginn des Anstiegs wie ein Abfall vom Wert beim
            # Umschalten aus.
            self.tw_start = min(self.tw_start, tw)
            self.tw_max = tw
            self.steigt = tw >= self.tw_start + ANSTIEG_BEGINNT_K
        elif self.tw_max - tw > MAX_ABFALL_K:
            self.fehler = "Speicher kuehlt waehrend der Ladung ab (gezapft?)"
        self.tw_max = max(self.tw_max, tw)


class LadungsKalibrierung:
    """Erkennt Warmwasser-Ladungen und rechnet daraus den Volumenstrom.

    ``messpunkt`` nach jedem Portalabruf aufrufen. Er liefert ``True``, wenn
    sich am Ergebnis etwas geaendert hat (Ladung gewertet oder verworfen).
    """

    def __init__(self, speicher_l: float) -> None:
        self.speicher_l = float(speicher_l)
        self.ladungen: list[dict[str, Any]] = []
        self.letzte_verworfen: str | None = None
        self._ladung: _Ladung | None = None

    # -- Ergebnis ------------------------------------------------------
    @property
    def aktiv(self) -> bool:
        return self.speicher_l > 0

    def wert(self) -> float | None:
        """Median der gueltigen Ladungen in m³/h, oder ``None``."""
        if len(self.ladungen) < MIN_LADUNGEN:
            return None
        return median(l["m3h"] for l in self.ladungen)

    @property
    def laeuft(self) -> bool:
        return self._ladung is not None

    def uebernehme(self, ladungen: Any) -> None:
        """Gespeicherte Ladungen nach einem Neustart wieder einlesen.

        Neu gerechnet aus Rohwerten, damit eine Aenderung des
        Speichervolumens auch die alten Ladungen richtig bewertet.
        """
        if not isinstance(ladungen, list):
            return
        uebernommen = []
        for l in ladungen[-ANZAHL_LADUNGEN:]:
            try:
                anstieg = float(l["anstieg_k"])
                integral = float(l["integral_kh"])
                eintrag = {
                    "ende": l.get("ende"),
                    "dauer_min": float(l.get("dauer_min", 0)),
                    "anstieg_k": anstieg,
                    "integral_kh": integral,
                }
            except (KeyError, TypeError, ValueError):
                continue
            if integral <= 0:
                continue
            eintrag["m3h"] = self._rechne(anstieg, integral)
            uebernommen.append(eintrag)
        self.ladungen = uebernommen

    def _rechne(self, anstieg_k: float, integral_kh: float) -> float:
        return round(self.speicher_l / 1000.0 * anstieg_k / integral_kh, 3)

    # -- Messpunkte ----------------------------------------------------
    def messpunkt(self, t: float, betriebsart: str | None, data: dict[str, Any]) -> bool:
        if not self.aktiv:
            return False
        tw = _zahl(data.get(PAR_SPEICHER))
        vor = _zahl(data.get(PAR_VORLAUF))
        rue = _zahl(data.get(PAR_RUECKLAUF))
        spreizung = None if vor is None or rue is None else vor - rue
        frequenz = _zahl(data.get(PAR_FREQUENZ))
        laedt = betriebsart == BETRIEBSART_LADUNG and bool(frequenz and frequenz > 0)

        ladung = self._ladung
        if ladung is None:
            if laedt and tw is not None and spreizung is not None:
                self._ladung = _Ladung(t, tw, spreizung)
            return False

        if ladung.t_ende is None:
            if laedt:
                ladung.punkt(t, tw, spreizung)
                return False
            # Ladung zu Ende. Abtauen mittendrin macht sie wertlos.
            if betriebsart == "Entfrosten":
                ladung.fehler = ladung.fehler or "Abtauen waehrend der Ladung"
            ladung.t_ende = ladung.t_letzt
            if ladung.fehler:
                return self._abschliessen()
            # weiter im Nachlauf

        # Nachlauf: Tw haengt nach, Maximum suchen
        if tw is not None:
            ladung.tw_max = max(ladung.tw_max, tw)
        if laedt or t - ladung.t_ende >= NACHLAUF_S:
            fertig = self._abschliessen()
            if laedt and tw is not None and spreizung is not None:
                self._ladung = _Ladung(t, tw, spreizung)
            return fertig
        return False

    def _abschliessen(self) -> bool:
        ladung = self._ladung
        self._ladung = None
        if ladung is None:
            return False
        grund = ladung.fehler
        dauer = (ladung.t_ende or ladung.t_letzt) - ladung.t_start
        anstieg = ladung.tw_max - ladung.tw_start
        integral_kh = ladung.integral_ks / 3600.0
        if grund is None and dauer < MIN_DAUER_S:
            grund = f"zu kurz ({dauer / 60:.0f} min)"
        if grund is None and anstieg < MIN_ANSTIEG_K:
            grund = f"Speicher nur {anstieg:.1f} K waermer"
        if grund is None and integral_kh < MIN_INTEGRAL_KH:
            grund = "Spreizung zu klein"
        if grund is None:
            m3h = self._rechne(anstieg, integral_kh)
            if not PLAUSIBEL_M3H[0] <= m3h <= PLAUSIBEL_M3H[1]:
                grund = f"unplausibel ({m3h:.2f} m³/h)"
        if grund is not None:
            self.letzte_verworfen = grund
            return True
        self.letzte_verworfen = None
        self.ladungen.append({
            "ende": ladung.t_ende,
            "dauer_min": round(dauer / 60.0, 1),
            "anstieg_k": round(anstieg, 2),
            "integral_kh": round(integral_kh, 4),
            "m3h": m3h,
        })
        self.ladungen = self.ladungen[-ANZAHL_LADUNGEN:]
        return True


def wirksame_volumenstroeme(
    modus: str,
    flow_heating: float,
    flow_dhw: float,
    kalibriert: float | None,
) -> tuple[float, float]:
    """(Heizen, Warmwasser) in m³/h nach Kalibrier-Modus.

    Ohne kalibrierten Wert bleiben die eingestellten Konstanten.
    """
    if kalibriert is None or modus not in (KALIBRIERUNG_WARMWASSER, KALIBRIERUNG_BEIDE):
        return flow_heating, flow_dhw
    if modus == KALIBRIERUNG_BEIDE:
        return kalibriert, kalibriert
    return flow_heating, kalibriert
