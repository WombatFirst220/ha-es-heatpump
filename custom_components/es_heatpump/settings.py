"""Katalog der schreibbaren Geraeteparameter (Portal-Seite "setdata").

ACHTUNG - ZWEI GETRENNTE NAMENSRAEUME
=====================================
Das Portal kennt ``parXX`` zweimal, mit voellig verschiedener Bedeutung:

  /a/amt/realdata/get   Messwerte   par1 = aktuelle Betriebsart, par4 = Vorlauf Tuo
  /a/amt/setdata/get    Einstellungen par1 = Anlage ein/aus,     par4 = Betriebsart-Vorwahl

Die Schluessel in DIESEM Modul gehoeren ausschliesslich zum *setdata*-Raum.
Sie duerfen nie gegen ``PARAMETER_SENSORS`` aus const.py gehalten werden.
Deshalb tragen alle Entities hier das Praefix ``es_hp_cfg_``.

Erzeugt am 22.09.2026 aus ``/a/amt/setdata/form`` des Geraets AW12-R32-M-V8.
Das Formular liefert Beschriftung, Typ, Wertebereich und die Auswahllisten
serverseitig mit - der Katalog ist also abgelesen, nicht geraten.

Alle Einstellungen sind standardmaessig aktiv (``enabled_default=True``). Sie
tragen ``EntityCategory.CONFIG``, erscheinen also unter "Konfiguration" auf der
Geraeteseite und nicht zwischen den Messwerten. Der Grund fuer die Entscheidung:
Eine abgeschaltete Entity liefert **gar keine** Daten - weder an eine Statistik
noch an eine externe Zeitreihendatenbank. Gerade die Werte, die man ueber Jahre
beobachten will (die fuenf Stuetzstellen jeder Heizkurve), waeren damit die
einzigen ohne Verlauf gewesen.

Das Modul ist bewusst frei von Home-Assistant-Importen und laesst sich ohne
HA testen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Art der Einstellung
KIND_NUMBER = "number"
KIND_SELECT = "select"
KIND_SWITCH = "switch"
KIND_READONLY = "readonly"   # wird gesichert, aber nie geschrieben


@dataclass(frozen=True)
class Setting:
    """Eine Einstellung, wie das Portal sie anbietet."""

    par: str
    group: str
    name: str
    kind: str
    portal_label: str
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0
    unit: str | None = None
    device_class: str | None = None
    options: dict[int, str] = field(default_factory=dict)
    enabled_default: bool = False

    @property
    def slug(self) -> str:
        """Entity-Slug, immer mit cfg-Praefix gegen Verwechslung mit Messwerten."""
        return f"cfg_{self.par}"

    @property
    def writable(self) -> bool:
        return self.kind != KIND_READONLY

    def validate(self, value: Any) -> int:
        """Prueft einen Wert gegen den Katalog und liefert ihn als int zurueck.

        Das Geraet nimmt ausschliesslich ganze Zahlen entgegen; das Portal
        sendet den Feldwert unveraendert weiter. Eine Pruefung hier ist die
        einzige Stelle, an der ein Tippfehler noch abgefangen wird, bevor er
        in der Waermepumpe landet.
        """
        if not self.writable:
            raise ValueError(f"{self.par} ({self.name}) ist nicht schreibbar")
        try:
            zahl = int(round(float(value)))
        except (TypeError, ValueError) as err:
            raise ValueError(f"{self.par}: {value!r} ist keine Zahl") from err
        if self.kind == KIND_SWITCH:
            if zahl not in (0, 1):
                raise ValueError(f"{self.par}: nur 0 oder 1 erlaubt, nicht {zahl}")
            return zahl
        if self.kind == KIND_SELECT:
            if zahl not in self.options:
                erlaubt = ", ".join(str(k) for k in sorted(self.options))
                raise ValueError(f"{self.par}: {zahl} nicht in [{erlaubt}]")
            return zahl
        if self.minimum is not None and zahl < self.minimum:
            raise ValueError(f"{self.par}: {zahl} unter dem Minimum {self.minimum:g}")
        if self.maximum is not None and zahl > self.maximum:
            raise ValueError(f"{self.par}: {zahl} ueber dem Maximum {self.maximum:g}")
        return zahl


SETTINGS: dict[str, Setting] = {

    # ── Schnelleinstellung ──────────────────────────────────────────
    "par1": Setting(
        par="par1", group="Schnelleinstellung",
        name="Anlage ein/aus",
        kind="switch", portal_label="Unit ON OFF",
        enabled_default=True,
    ),
    "par4": Setting(
        par="par4", group="Schnelleinstellung",
        name="Betriebsart",
        kind="select", portal_label="Working Mode",
        options={0: "Bereitschaft", 1: "Heizen", 2: "Kühlen", 3: "Warmwasser", 4: "Automatik"},
        enabled_default=True,
    ),
    "par5": Setting(
        par="par5", group="Schnelleinstellung",
        name="Sprache der Bedieneinheit",
        kind="select", portal_label="Language",
        options={0: "English", 1: "Slovenščina", 10: "English", 11: "English", 12: "English", 13: "English", 14: "English", 15: "中文", 2: "Deutsch", 3: "Polski", 4: "Italiano", 5: "Русский", 6: "Українська", 7: "Polski", 8: "English", 9: "English"},
        enabled_default=True,
    ),
    "par36": Setting(
        par="par36", group="Schnelleinstellung",
        name="Wunsch-Raumtemperatur Heizen",
        kind="number", portal_label="Ideal Room temp. in Heating",
        minimum=15, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par37": Setting(
        par="par37", group="Schnelleinstellung",
        name="Wunsch-Raumtemperatur Kühlen",
        kind="number", portal_label="Ideal Room temp. in Cooling",
        minimum=15, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par55": Setting(
        par="par55", group="Schnelleinstellung",
        name="Warmwasser Solltemperatur",
        kind="number", portal_label="Setpoint DHW",
        minimum=25, maximum=75, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par121": Setting(
        par="par121", group="Schnelleinstellung",
        name="Parallelverschiebung Heizkurve 1",
        kind="number", portal_label="Curve 1 Parallel Move",
        minimum=-3, maximum=3, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par122": Setting(
        par="par122", group="Schnelleinstellung",
        name="Parallelverschiebung Heizkurve 2",
        kind="number", portal_label="Curve 2 Parallel Move",
        minimum=-3, maximum=3, unit="°C", device_class="temperature",
        enabled_default=True,
    ),

    # ── Heiz-/Kühlkreis 2 ───────────────────────────────────────────
    "par67": Setting(
        par="par67", group="Heiz-/Kühlkreis 2",
        name="Heiz-/Kühlkreis 2",
        kind="switch", portal_label="Heating&cooling Circuit 2",
        enabled_default=True,
    ),
    "par68": Setting(
        par="par68", group="Heiz-/Kühlkreis 2",
        name="Solltemperatur Kühlen (Kreis 2)",
        kind="number", portal_label="Set temp. For Cooling",
        minimum=0, maximum=100, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par75": Setting(
        par="par75", group="Heiz-/Kühlkreis 2",
        name="Solltemperatur Heizen Kreis 2 (ohne Heizkurve)",
        kind="number", portal_label="Set Temp. for Heating (without heating curve)",
        minimum=0, maximum=100, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par69": Setting(
        par="par69", group="Heiz-/Kühlkreis 2",
        name="Heizkurve Kreis 2",
        kind="switch", portal_label="Heating Curve",
        enabled_default=True,
    ),
    "par70": Setting(
        par="par70", group="Heiz-/Kühlkreis 2",
        name="Heizkurve 2 Stützstelle 1 – Wassertemperatur",
        kind="number", portal_label="Water Temp. A/Ambient Temp. 1",
        minimum=-666, maximum=666, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par71": Setting(
        par="par71", group="Heiz-/Kühlkreis 2",
        name="Heizkurve 2 Stützstelle 2 – Wassertemperatur",
        kind="number", portal_label="Water Temp. B/Ambient Temp. 2",
        minimum=-666, maximum=666, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par72": Setting(
        par="par72", group="Heiz-/Kühlkreis 2",
        name="Heizkurve 2 Stützstelle 3 – Wassertemperatur",
        kind="number", portal_label="Water Temp. C/Ambient Temp. 3",
        minimum=-666, maximum=666, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par73": Setting(
        par="par73", group="Heiz-/Kühlkreis 2",
        name="Heizkurve 2 Stützstelle 4 – Wassertemperatur",
        kind="number", portal_label="Water Temp. D/Ambient Temp .4",
        minimum=-666, maximum=666, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par74": Setting(
        par="par74", group="Heiz-/Kühlkreis 2",
        name="Heizkurve 2 Stützstelle 5 – Wassertemperatur",
        kind="number", portal_label="Water Temp. E/Ambient Temp. 5",
        minimum=-666, maximum=666, unit="°C", device_class="temperature",
        enabled_default=True,
    ),

    # ── Warmwasserspeicher ──────────────────────────────────────────
    "par63": Setting(
        par="par63", group="Warmwasserspeicher",
        name="Warmwasserspeicher-Funktion",
        kind="switch", portal_label="Sanitary Hot Water Storage Function",
        enabled_default=True,
    ),
    "par64": Setting(
        par="par64", group="Warmwasserspeicher",
        name="Nachheizfunktion",
        kind="switch", portal_label="Reheating Function",
        enabled_default=True,
    ),
    "par65": Setting(
        par="par65", group="Warmwasserspeicher",
        name="Nachheizen Solltemperatur",
        kind="number", portal_label="Reheating Set Temp.",
        minimum=25, maximum=55, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par66": Setting(
        par="par66", group="Warmwasserspeicher",
        name="Nachheizen Wiedereinschalt-Spreizung",
        kind="number", portal_label="Reheating Restart ∆T Setting",
        minimum=2, maximum=20, unit="K", device_class=None,
        enabled_default=True,
    ),

    # ── Legionellenschutz ───────────────────────────────────────────
    "par41": Setting(
        par="par41", group="Legionellenschutz",
        name="Legionellenschutz",
        kind="switch", portal_label="Anti-Legionella Program",
        enabled_default=True,
    ),
    "par42": Setting(
        par="par42", group="Legionellenschutz",
        name="Legionellenschutz Solltemperatur",
        kind="number", portal_label="Setpoint",
        minimum=60, maximum=80, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par43": Setting(
        par="par43", group="Legionellenschutz",
        name="Legionellenschutz Dauer",
        kind="number", portal_label="Duration",
        minimum=5, maximum=60, unit="min", device_class=None,
        enabled_default=True,
    ),
    "par44": Setting(
        par="par44", group="Legionellenschutz",
        name="Legionellenschutz Abschlusszeit",
        kind="number", portal_label="Finish Time",
        minimum=10, maximum=180, unit="min", device_class=None,
        enabled_default=True,
    ),

    # ── Benutzerverwaltung ──────────────────────────────────────────
    "par19": Setting(
        par="par19", group="Benutzerverwaltung",
        name="Zeitprogramm Heizen/Kühlen",
        kind="switch", portal_label="Heating/Cooling ON/OFF Timer",
        enabled_default=True,
    ),

    # ── Zusatzheizung ───────────────────────────────────────────────
    "par48": Setting(
        par="par48", group="Zusatzheizung",
        name="Zusatzheizung für Heizbetrieb",
        kind="switch", portal_label="Backup Heating Sources For Heating",
        enabled_default=True,
    ),
    "par49": Setting(
        par="par49", group="Zusatzheizung",
        name="Vorrang Zusatzheizung Heizen (HBH)",
        kind="select", portal_label="Priority for Backup Heating Sources (HBH)",
        options={0: "Niedriger als Wärmepumpe", 1: "Höher als Wärmepumpe"},
        enabled_default=True,
    ),
    "par50": Setting(
        par="par50", group="Zusatzheizung",
        name="Zusatzheizung für Warmwasser",
        kind="switch", portal_label="Backup Heating Source for Sanitary Hot Water",
        enabled_default=True,
    ),
    "par51": Setting(
        par="par51", group="Zusatzheizung",
        name="Vorrang Zusatzheizung Warmwasser (HWTBH)",
        kind="select", portal_label="Priority for Backup Heating Sources (HWTBH)",
        options={0: "Niedriger als Wärmepumpe", 1: "Höher als Wärmepumpe"},
        enabled_default=True,
    ),
    "par52": Setting(
        par="par52", group="Zusatzheizung",
        name="Startschwelle Zusatzheizung (HBH)",
        kind="number", portal_label="Heating Source Start Accumulating Value (HBH)",
        minimum=5, maximum=600, unit=None, device_class=None,
        enabled_default=True,
    ),
    "par53": Setting(
        par="par53", group="Zusatzheizung",
        name="Leseintervall Wassertemperaturanstieg (HWTBH)",
        kind="number", portal_label="Water Temperature Rise Reading Interval (HWTBH)",
        minimum=5, maximum=180, unit="min", device_class=None,
        enabled_default=True,
    ),

    # ── Weitere Optionen ────────────────────────────────────────────
    "par86": Setting(
        par="par86", group="Weitere Optionen",
        name="Displaybeleuchtung",
        kind="select", portal_label="Control Panel Backlight Light",
        options={0: "Dauernd an", 1: "3 Minuten", 2: "5 Minuten", 3: "10 Minuten"},
        enabled_default=True,
    ),

    # ── Heiz-/Kühlkreis 1 ───────────────────────────────────────────
    "par20": Setting(
        par="par20", group="Heiz-/Kühlkreis 1",
        name="Abschaltung bei Wasser-Spreizung",
        kind="number", portal_label="Heating/Cooling Stops Based on Water ∆T",
        minimum=1, maximum=3, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par21": Setting(
        par="par21", group="Heiz-/Kühlkreis 1",
        name="Wiedereinschaltung bei Wasser-Spreizung",
        kind="number", portal_label="Heating/Cooling Restarts Based on Water ∆T",
        minimum=1, maximum=10, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par22": Setting(
        par="par22", group="Heiz-/Kühlkreis 1",
        name="Spreizung für Verdichterdrosselung",
        kind="number", portal_label="∆T Compressor Speed-reduction",
        minimum=1, maximum=10, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par23": Setting(
        par="par23", group="Heiz-/Kühlkreis 1",
        name="Solltemperatur Kühlen (Kreis 1)",
        kind="number", portal_label="Set temp. for Cooling",
        minimum=0, maximum=100, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par24": Setting(
        par="par24", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Kreis 1",
        kind="switch", portal_label="Heating Curve",
        enabled_default=True,
    ),
    "par25": Setting(
        par="par25", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 1 – Außentemperatur",
        kind="number", portal_label="Ambient Temp. 1",
        minimum=-25, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par26": Setting(
        par="par26", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 2 – Außentemperatur",
        kind="number", portal_label="Ambient Temp. 2",
        minimum=-25, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par27": Setting(
        par="par27", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 3 – Außentemperatur",
        kind="number", portal_label="Ambient Temp. 3",
        minimum=-25, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par28": Setting(
        par="par28", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 4 – Außentemperatur",
        kind="number", portal_label="Ambient Temp. 4",
        minimum=-25, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par29": Setting(
        par="par29", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 5 – Außentemperatur",
        kind="number", portal_label="Ambient Temp. 5",
        minimum=-25, maximum=35, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par30": Setting(
        par="par30", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 1 – Wassertemperatur",
        kind="number", portal_label="Water Temp. A /Ambient Temp. 1",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par31": Setting(
        par="par31", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 2 – Wassertemperatur",
        kind="number", portal_label="Water Temp. B/Ambient Temp. 2",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par32": Setting(
        par="par32", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 3 – Wassertemperatur",
        kind="number", portal_label="Water Temp. C/Ambient Temp. 3",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par33": Setting(
        par="par33", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 4 – Wassertemperatur",
        kind="number", portal_label="Water Temp. D/Ambient Temp .4",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par34": Setting(
        par="par34", group="Heiz-/Kühlkreis 1",
        name="Heizkurve Stützstelle 5 – Wassertemperatur",
        kind="number", portal_label="Water Temp. E/Ambient Temp. 5",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par35": Setting(
        par="par35", group="Heiz-/Kühlkreis 1",
        name="Raumtemperatur wirkt auf Heizkurve",
        kind="switch", portal_label="Room temp. effect on Heating Curve",
        enabled_default=True,
    ),
    "par38": Setting(
        par="par38", group="Heiz-/Kühlkreis 1",
        name="Solltemperatur Heizen (ohne Heizkurve)",
        kind="number", portal_label="Set temp. for Heating (without heating curve)",
        minimum=20, maximum=60, unit="°C", device_class="temperature",
        enabled_default=True,
    ),

    # ── Warmwasser ──────────────────────────────────────────────────
    "par56": Setting(
        par="par56", group="Warmwasser",
        name="Warmwasser Wiedereinschalt-Spreizung",
        kind="number", portal_label="DHW Restart ∆T Setting",
        minimum=2, maximum=15, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par57": Setting(
        par="par57", group="Warmwasser",
        name="Vorrangumschaltung",
        kind="switch", portal_label="Shifting Priority",
        enabled_default=True,
    ),
    "par58": Setting(
        par="par58", group="Warmwasser",
        name="Vorrangumschaltung ab Außentemperatur",
        kind="number", portal_label="Shifting Priority Stating Temp.",
        minimum=-15, maximum=20, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par59": Setting(
        par="par59", group="Warmwasser",
        name="Warmwasser Mindestlaufzeit",
        kind="number", portal_label="Sanitary Water Min. Working Hours",
        minimum=10, maximum=60, unit="min", device_class=None,
        enabled_default=True,
    ),
    "par60": Setting(
        par="par60", group="Warmwasser",
        name="Heizen Maximallaufzeit",
        kind="number", portal_label="Heating Max. Working Hours",
        minimum=30, maximum=180, unit="min", device_class=None,
        enabled_default=True,
    ),
    "par61": Setting(
        par="par61", group="Warmwasser",
        name="Zulässige Temperaturabweichung Heizen",
        kind="number", portal_label="Allowable temp Drift in Heating",
        minimum=3, maximum=10, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par62": Setting(
        par="par62", group="Warmwasser",
        name="Warmwasser-Zusatzheizung bei Vorrangumschaltung",
        kind="switch", portal_label="DHW Backup Heater for Shifting Priority",
        enabled_default=True,
    ),

    # ── Absenkbetrieb Heizen ────────────────────────────────────────
    "par78": Setting(
        par="par78", group="Absenkbetrieb Heizen",
        name="Absenkbetrieb",
        kind="switch", portal_label="Reduced Setpoint",
        enabled_default=True,
    ),
    "par79": Setting(
        par="par79", group="Absenkbetrieb Heizen",
        name="Absenkung/Anhebung",
        kind="number", portal_label="Temp. Drop/Rise",
        minimum=2, maximum=10, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par80": Setting(
        par="par80", group="Absenkbetrieb Heizen",
        name="Flüsterbetrieb",
        kind="switch", portal_label="Quiet Operation",
        enabled_default=True,
    ),
    "par81": Setting(
        par="par81", group="Absenkbetrieb Heizen",
        name="Zulässige Temperaturabweichung im Absenkbetrieb",
        kind="number", portal_label="Allowable Temp. Drifting",
        minimum=2, maximum=10, unit="K", device_class=None,
        enabled_default=True,
    ),

    # ── Urlaubsmodus ────────────────────────────────────────────────
    "par45": Setting(
        par="par45", group="Urlaubsmodus",
        name="Urlaubsmodus",
        kind="switch", portal_label="Vacation Mode",
        enabled_default=True,
    ),
    "par46": Setting(
        par="par46", group="Urlaubsmodus",
        name="Warmwasser-Absenkung im Urlaub",
        kind="number", portal_label="Sanitary Hot Water temp. Drop during Vacation Mode",
        minimum=10, maximum=50, unit="K", device_class=None,
        enabled_default=True,
    ),
    "par47": Setting(
        par="par47", group="Urlaubsmodus",
        name="Heizwasser-Absenkung im Urlaub",
        kind="number", portal_label="Heating Water temp. Drop during Vacation Mode",
        minimum=10, maximum=50, unit="K", device_class=None,
        enabled_default=True,
    ),

    # ── Betriebsart-Umschaltung ─────────────────────────────────────
    "par9": Setting(
        par="par9", group="Betriebsart-Umschaltung",
        name="Umschaltung Heizen/Kühlen",
        kind="select", portal_label="Cooling and Heating Switch",
        options={0: "Deaktiviert", 1: "Außentemperatur", 2: "Externes Signal", 3: "Externes Signal + Außentemperatur"},
        enabled_default=True,
    ),
    "par11": Setting(
        par="par11", group="Betriebsart-Umschaltung",
        name="Außentemperatur Heizen ab",
        kind="number", portal_label="Ambient Temp. To Start Heating",
        minimum=-10, maximum=25, unit="°C", device_class="temperature",
        enabled_default=True,
    ),
    "par12": Setting(
        par="par12", group="Betriebsart-Umschaltung",
        name="Außentemperatur Kühlen ab",
        kind="number", portal_label="Ambient Temp. To Start Cooling",
        minimum=8, maximum=53, unit="°C", device_class="temperature",
        enabled_default=True,
    ),

    # ── EVU-Sperre ──────────────────────────────────────────────────
    "par83": Setting(
        par="par83", group="EVU-Sperre",
        name="EVU-Sperre",
        kind="switch", portal_label="Electrical Utility Lock",
        enabled_default=True,
    ),
    "par84": Setting(
        par="par84", group="EVU-Sperre",
        name="Zusatzheizung während EVU-Sperre",
        kind="switch", portal_label="HBH During Electrical Utility Lock",
        enabled_default=True,
    ),
    "par85": Setting(
        par="par85", group="EVU-Sperre",
        name="Umwälzpumpe P0 während EVU-Sperre",
        kind="switch", portal_label="P0 during Electrical Utility Lock",
        enabled_default=True,
    ),

    # ── Systeminformation ───────────────────────────────────────────
    "par2": Setting(
        par="par2", group="Systeminformation",
        name="Softwareversion",
        kind="readonly", portal_label="Software Version No.",
        enabled_default=True,
    ),
    "par3": Setting(
        par="par3", group="Systeminformation",
        name="Datenbankversion",
        kind="readonly", portal_label="Database Version",
        enabled_default=True,
    ),
    "par137": Setting(
        par="par137", group="Systeminformation",
        name="Softwareversion Wärmepumpen-Platine",
        kind="readonly", portal_label="HeatPump PCB Software Version No.",
        enabled_default=True,
    ),
    "par138": Setting(
        par="par138", group="Systeminformation",
        name="EEPROM-Version Außenplatine",
        kind="readonly", portal_label="Outdoor PCB EEPROM Version",
        enabled_default=True,
    ),
}

# Reihenfolge der Gruppen, wie das Portal sie zeigt
GROUPS: list[str] = []
for _s in SETTINGS.values():
    if _s.group not in GROUPS:
        GROUPS.append(_s.group)

WRITABLE: dict[str, Setting] = {k: v for k, v in SETTINGS.items() if v.writable}


def beschreibe(par: str, wert: Any) -> str:
    """Menschenlesbare Fassung eines Wertes - fuer Diffs und Protokolle."""
    s = SETTINGS.get(par)
    if s is None:
        return f"{par} = {wert}"
    if s.kind == KIND_SWITCH:
        return f"{s.name}: {'Ein' if int(wert) else 'Aus'}"
    if s.kind == KIND_SELECT:
        return f"{s.name}: {s.options.get(int(wert), wert)}"
    einheit = f" {s.unit}" if s.unit else ""
    return f"{s.name}: {wert:g}{einheit}" if isinstance(wert, (int, float)) else f"{s.name}: {wert}"
