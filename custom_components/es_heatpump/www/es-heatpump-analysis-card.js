/*
 * ES Heatpump – Auswertung (custom:es-heatpump-analysis-card)
 * ─────────────────────────────────────────────────────────────
 * Teil der Integration es_heatpump (ab v4.0.0). Vanilla Web Component ohne
 * Build-Schritt und ohne externe Abhaengigkeiten; Diagramme als selbst
 * gezeichnetes SVG.
 *
 * Datenquellen:
 *   - recorder/statistics_during_period (Langzeitstatistik von Home Assistant)
 *   - es_heatpump/settings_changes (Einstellungsaenderungen aus der
 *     Sicherungsablage der Integration)
 *   - es_heatpump/analysis_config (Entity-IDs, ab v4.0.1; fehlt der Befehl,
 *     gelten die Standard-IDs)
 *
 * Quellenwahl je Balken (v4.0.1): Die Energiezaehler der Integration gibt es
 * erst seit dem Update auf v4.0.0. Deckt ihre Statistik einen Balken nicht
 * vollstaendig ab (erster Statistik-Zeitpunkt nach Balkenbeginn), kommt der
 * Strom aus dem konfigurierten Stromzaehler (change) oder - geschaetzt - aus
 * dem Mittel der elektrischen Leistung x abgedeckte Stunden, die Waerme aus
 * dem Mittel der thermischen Leistung. Dafuer wird immer die
 * Stundenstatistik summiert (fehlende Stunden = keine Daten, nie
 * hochgerechnet); bei mehr als ~62 Tagen nur bis zum Ende des Monats, in dem
 * die Zaehler beginnen. Heizen/Warmwasser, Starts und Laufzeit gibt es nur aus
 * den Zaehlern.
 *
 * Arbeitszahl (v4.0.1): nur aus Stunden mit Strom UND Waerme (bei den
 * Zaehlern der Integration aus dem ganzen Balken); Tage mit AZ < 1 bei
 * nennenswertem Strom sind physikalisch unmoeglich und zaehlen nicht (hohler
 * Punkt, Hinweis). Vorzeitraum-Deltas nur bei vergleichbarer Datenabdeckung.
 *
 * Carnot-Guetegrad (v1.3.0, Integration v4.1.0): waermegewichtet aus
 * Stundenwerten wie in heatpumpmonitor.org ("weighted_kwh_carnot_elec"):
 *   COP_Carnot(h) = (Tv + 2 + 273,15) / ((Tv + 2) - (Ta - 6))
 *   Guetegrad     = Summe Waerme(h) / Summe(Strom(h) x COP_Carnot(h))
 * mit Tv/Ta = Stundenmittel von Vorlauf und Aussentemperatur; nur Stunden mit
 * Strom UND Waerme > 0 (Verdichter lief), Nenner > 1 K und ohne unplausible
 * Tage (wie die Arbeitszahl). Offsets wie energy.cop_carnot. Wo es keine
 * Stundenwerte gibt (lange Zeitraeume nach Beginn der Zaehler), aus
 * Tageswerten (Kennzeichnung "aus Tagesmitteln").
 *
 * Standby (v1.3.0): Zaehler el_standby, nur wenn seine Statistik den ganzen
 * Zeitraum abdeckt. Takten: Starts je Laufstunde mit denselben Schwellen wie
 * binary_sensor.es_hp_takten.
 *
 * Statistiken werden nur bei Zeitraumwechsel und alle 10 Minuten neu geladen,
 * nicht bei jedem hass-Update.
 */

const CARD_VERSION = "1.4.0";
const REFRESH_MS = 10 * 60 * 1000;
const MIN_EL_KWH = 0.05;          // Arbeitszahl je Balken erst ab dieser Strommenge
const AZ_AXIS_MAX = 8;            // Arbeitszahl-Achse wird hier gekappt
const TEMP_HINT_K = 3;            // Aussentemperatur-Unterschied fuer den Hinweis
const DAY_MS = 86400000;
const HOUR_MS = 3600000;
const HOURLY_MAX_DAYS = 62;       // bis zu dieser Spanne Leistungsmittel fuer den ganzen Zeitraum
// Plausibilitaet der Arbeitszahl: Ein Tag mit mindestens 0,5 kWh Strom (je
// Tag-Aequivalent, bei weniger Stunden anteilig) und weniger Waerme als Strom
// ist physikalisch unmoeglich - eine Waermepumpe gibt immer mehr Waerme ab, als
// sie Strom aufnimmt. Darunter liegt reiner Bereitschaftsbetrieb (~15 W), dort
// ist AZ < 1 normal. Ursache war bisher ein zu niedrig eingestellter
// Volumenstrom (Waerme zu klein berechnet).
const IMPLAUSIBLE_EL_DAY = 0.5;
const IMPLAUSIBLE_AZ = 1;
// Vorzeitraum-Delta nur, wenn dessen Datenabdeckung mindestens 80 % der
// Abdeckung des aktuellen Zeitraums erreicht (sonst vergleicht man z. B. ein
// halbes mit einem ganzen Jahr).
const PREV_COVERAGE_MIN = 0.8;
// Praktischer Carnot-COP, Offsets wie energy.py (CARNOT_OFFSET_KONDENSATION_K,
// CARNOT_OFFSET_VERDAMPFUNG_K, CARNOT_MIN_HUB_K) und const.TEMP_SENTINEL
const CARNOT_COND_K = 2;
const CARNOT_EVAP_K = -6;
const CARNOT_MIN_HUB_K = 1;
const TEMP_SENTINEL = -99;
// Takt-Schwellen wie binary_sensor.es_hp_takten (energy.py:
// TAKT_MAX_STARTS_JE_STUNDE, TAKT_MIN_LAUFZEIT_MIN) - dort begruendet
const TAKT_MAX_STARTS_PER_H = 3;
const TAKT_MIN_RUN_MIN = 10;
// Verdichterzyklen aus dem Zustandsverlauf (v1.4.0): Luecken (unavailable/
// unknown) bis hierhin werden ueberbrueckt, wie energy.MAX_LUECKE_VERDICHTER_S
const CYCLE_GAP_MS = 10 * 60 * 1000;
const CYCLE_BINS = [10, 20, 40, 60, 120];   // Klassengrenzen der Histogramme (min)
const CYCLE_MODES = ["heating", "dhw", "defrost", "cooling", "other"];
const CYCLE_VIEWS = ["day", "week", "month"];
const HIST_STALE_MS = 5 * 60 * 1000;        // laufender Tag: Verlauf hoechstens so alt
const HIST_PROBE_DAYS = 400;                // Suche nach dem Beginn des Verlaufs
const HIST_DAY_COV = 0.9;                   // Tag gilt ab diesem Anteil als abgedeckt (Vergleich)
const MODE_ALIASES = {
  heating: "heating", heizen: "heating",
  dhw: "dhw", brauchwasser: "dhw", warmwasser: "dhw", dhw_heating: "dhw", dhw_cooling: "dhw",
  "brauchwasser + heizen": "dhw", "brauchwasser + kuehlen": "dhw", "brauchwasser + kühlen": "dhw",
  defrost: "defrost", entfrosten: "defrost", abtauen: "defrost",
  cooling: "cooling", kuehlen: "cooling", "kühlen": "cooling",
};

const DEFAULT_ENTITIES = {
  el: "sensor.es_hp_energie_elektrisch",
  el_heat: "sensor.es_hp_energie_elektrisch_heizen",
  el_dhw: "sensor.es_hp_energie_elektrisch_warmwasser",
  th: "sensor.es_hp_energie_thermisch",
  th_heat: "sensor.es_hp_energie_thermisch_heizen",
  th_dhw: "sensor.es_hp_energie_thermisch_warmwasser",
  el_standby: "sensor.es_hp_energie_elektrisch_standby",
  starts: "sensor.es_hp_verdichter_starts",
  runtime: "sensor.es_hp_verdichter_laufzeit",
  outdoor: "sensor.es_hp_aussentemp_ta",
  cop: "sensor.es_hp_aktueller_cop",
  flow: "sensor.es_hp_vorlauf_tuo",
  el_power: "sensor.es_hp_leistung_elektrisch",
  th_power: "sensor.es_hp_thermische_leistung",
  meter: null,                    // Stromzaehler (kWh) aus den Optionen
  frequency: "sensor.es_hp_frequenz_hz",   // Verdichterzyklen (Verlauf)
  mode: "sensor.es_hp_betriebsart",
};
const SUM_KEYS = ["el", "el_heat", "el_dhw", "el_standby", "th", "th_heat", "th_dhw", "starts", "runtime"];
const MEAN_KEYS = ["outdoor", "cop", "flow"];
const POWER_KEYS = ["el_power", "th_power"];
// Antwort von es_heatpump/analysis_config -> Schluessel der Karte
const WS_KEYS = { outdoor: "outdoor", cop: "cop", flow: "flow", el_power: "electrical_power", th_power: "thermal_power", meter: "energy_entity",
  frequency: "frequency", mode: "mode" };
const VIEWS = ["day", "week", "month", "year", "all"];

// ─────────────────────────────────────────────────────────────────────────────
// Texte
// ─────────────────────────────────────────────────────────────────────────────
const I18N = {
  de: {
    title: "Auswertung",
    view_day: "Tag", view_week: "Woche", view_month: "Monat", view_year: "Jahr", view_all: "Alle Jahre",
    prev: "Zurück", next: "Weiter", today: "Heute", all_years: "Alle Jahre", week_short: "KW",
    loading: "Lade Statistiken …",
    err_stats: "Statistiken konnten nicht geladen werden",
    err_changes: "Einstellungsänderungen sind nicht verfügbar",
    missing_entity: "Die Energiezähler ({id}) sind noch nicht vorhanden. Bitte die Integration aktualisieren und Home Assistant neu starten.",
    no_data_yet: "Noch keine Daten — die Zähler laufen, die ersten Statistiken erscheinen spätestens nach einer Stunde.",
    no_data_range: "Keine Daten in diesem Zeitraum — die ersten Werte stammen vom {since}.",
    history_note: "Vor {since} (Start der Zähler der Integration) stammen die Werte aus der vorhandenen Statistik — {sources}. Diese Balken sind nicht nach Heizen/Warmwasser aufgeteilt, Starts und Laufzeit fehlen dort. Schraffiert = aus dem Leistungsmittel geschätzt.",
    history_note_nocounter: "Die Zähler der Integration haben noch keine Statistik; die Werte stammen aus der vorhandenen Statistik — {sources}. Ohne Aufteilung nach Heizen/Warmwasser, ohne Starts und Laufzeit. Schraffiert = aus dem Leistungsmittel geschätzt.",
    src: "Quelle", src_counter: "Zähler der Integration", src_meter: "Stromzähler", src_meter_shelly: "Shelly-Zähler", src_mean: "aus Leistungsmittel",
    unsplit: "nicht aufgeteilt", estimated: "geschätzt",
    only_since: "nur ab {since}", only_counters: "Erst seit Start der Zähler ({since}) verfügbar.",
    hint_estimated: "Ein Teil der Werte stammt aus der Statistik vor den Zählern der Integration ({sources}); Starts und Laufzeit fehlen dort.",
    el: "Strom", th: "Wärme", az: "Arbeitszahl", temp: "Außentemp.",
    heat: "Heizen", dhw: "Warmwasser", rest: "Sonstiges",
    k_el: "Strom", k_th: "Wärme", k_az: "Arbeitszahl", k_az_heat: "AZ Heizen", k_az_dhw: "AZ Warmwasser",
    k_dhw_share: "Warmwasser-Anteil", k_starts: "Verdichterstarts", k_runtime: "Laufzeit",
    k_run_per_start: "Laufzeit je Start", k_outdoor: "Ø Außentemp.", k_hdd: "Heizgradtage",
    k_kwh_hdd: "Strom je HGT", k_flow: "Ø Vorlauf", k_cop: "Ø COP (Momentanwert)",
    vs_prev: "ggü. Vorzeitraum (gleiche Dauer)", vs_prev_none: "kein Vorzeitraum",
    hdd_hint: "HGT: Summe (Basis − Tagesmittel) über Tage unter {base} °C",
    changes: "Einstellungsänderungen", changes_none: "Keine Einstellungsänderungen erfasst. Änderungen werden aus aufeinanderfolgenden Sicherungen abgeleitet.",
    changes_more: "Alle {n} anzeigen", changes_less: "Weniger anzeigen", in_range: "im Zeitraum",
    compare: "Vorher / Nachher", compare_days: "Tage", before: "Vorher", after: "Nachher", delta: "Δ",
    close: "Schließen",
    c_az: "Arbeitszahl", c_el_day: "Strom je Tag", c_th_day: "Wärme je Tag", c_kwh_hdd: "Strom je HGT",
    c_starts_day: "Starts je Tag", c_run_per_start: "Laufzeit je Start", c_outdoor: "Ø Außentemp.",
    c_flow: "Ø Vorlauf", c_days: "Tage mit Daten",
    hint_incomplete: "Der Zeitraum „nachher“ ist noch unvollständig ({n} von {m} Tagen).",
    hint_temp: "Die Außentemperatur unterscheidet sich um {d} K — die Arbeitszahl ist nur bedingt vergleichbar. Aussagekräftiger ist der Carnot-Gütegrad (weitgehend wetterunabhängig); Strom je Heizgradtag gleicht den Verbrauch teilweise aus.",
    hint_carnot: "Carnot-Gütegrad: erreichte Arbeitszahl im Verhältnis zur bei diesen Vorlauf- und Außentemperaturen theoretisch möglichen — wetterunabhängiger als die Arbeitszahl.",
    k_carnot: "Carnot-Gütegrad", c_carnot: "Carnot-Gütegrad", carnot_daily: "aus Tagesmitteln",
    carnot_title: "Wärme ÷ (Strom × Carnot-COP) aus Stundenwerten, nur Stunden mit laufendem Verdichter; COP_Carnot = (Tv+2+273,15) / ((Tv+2) − (Ta−6)). Wetterunabhängiger als die Arbeitszahl.",
    carnot_daily_title: "Für einen Teil des Zeitraums gibt es nur Tageswerte: Carnot-COP aus Tagesmitteln von Vorlauf und Außentemperatur (ungenauer, eher zu niedrig).",
    k_standby: "Standby", standby_sub: "Ø {w} W · {p} % des Stroms", from_date: "ab {since}",
    standby_title: "Stromverbrauch, während der Verdichter steht (Zähler „Energie elektrisch Standby“).",
    k_starts_h: "Starts je Laufstunde",
    takt_title: "Warnfarbe ab mehr als {n} Starts je Laufstunde bzw. unter {m} min Laufzeit je Start (wie der Binärsensor „Takten“).",
    pp: "%-Pkt.", g_energy: "Energie", g_eff: "Effizienz", g_ops: "Betrieb", g_weather: "Wetter",
    avail_from: "Erst ab {since} verfügbar: {list}", avail_none: "Noch keine Statistik: {list}",
    hint_overlap: "Im Vergleichszeitraum gab es weitere Änderungen ({n}) — die Wirkung lässt sich nicht eindeutig zuordnen.",
    hint_nodata: "Für diesen Zeitraum liegen keine Tageswerte vor.",
    hint_change_day: "Der Tag der Änderung selbst wird nicht mitgezählt.",
    show: "Anzeigen",
    az_partial: "nur Zeiten mit Strom + Wärme",
    az_partial_title: "Die Arbeitszahl wird nur aus Zeiten gebildet, in denen Strom und Wärme vorliegen ({p} % der Zeit mit Strom); unplausible Zeiten (AZ < 1) zählen nicht.",
    az_bad: "AZ unplausibel (nicht gezählt)",
    az_paired: "AZ aus {h} von {m} h",
    implausible_note: "Arbeitszahl < 1 ist physikalisch unmöglich – vermutlich war der Volumenstrom damals zu niedrig eingestellt; diese Zeiträume zählen nicht zur Arbeitszahl ({from} – {to}, {n} Tage). Strom und Wärme bleiben sichtbar, die Punkte sind hohl gezeichnet.",
    prev_incomplete: "Vorzeitraum unvollständig — Δ nur bei mindestens {p} % der Datenabdeckung",
    prev_incomplete_tile: "Vorzeitraum unvollständig ({p} % der Abdeckung)",
    hint_implausible: "Tage mit Arbeitszahl < 1 (physikalisch unmöglich, vermutlich zu niedriger Volumenstrom) zählen nicht zur Arbeitszahl.",
    reason: {
      "manuell": "Manuelle Sicherung", "automatisch": "Automatische Sicherung",
      "vor-schreibzugriff": "Vor Schreibzugriff", "vor-wiederherstellung": "Vor Wiederherstellung",
      "erstaufnahme": "Erstaufnahme",
    },
    tk_title: "Takten / Verdichterzyklen",
    tk_loading: "Lade Verlauf …",
    tk_err: "Verlauf konnte nicht geladen werden",
    tk_missing: "Die Frequenz-Entity ({id}) fehlt — ohne sie lassen sich keine Verdichterzyklen rekonstruieren.",
    tk_no_history: "Der Recorder hat keinen Verlauf der Verdichterfrequenz.",
    tk_no_data: "Für diesen Zeitraum gibt es keinen Verlauf mehr (Recorder hält ~{n} Tage, ab {since}) und keine Zähler-Statistik der Integration (ab {csince}).",
    tk_src_hist: "Aus dem Verlauf rekonstruiert (Recorder hält ~{n} Tage, ab {since})",
    tk_src_counter: "Starts und Laufzeit an {n} Tag(en) aus den Zählern der Integration",
    tk_src_short: "aus dem Verlauf rekonstruiert",
    tk_partial: "Verlauf erst ab {since} — ältere Tage nur aus den Zählern der Integration (ab {csince})",
    tk_mixed: "Min./Max., Pausen, Klassen und Aufteilung nur aus dem Verlauf",
    tk_long_hint: "Starts und Laufzeit je Zeitraum nur aus den Zählern der Integration (Statistik ab {since}). Einzelne Zyklen: Ansicht Tag, Woche oder Monat (Verlauf der letzten ~{n} Tage).",
    tk_long_none: "Starts und Laufzeit je Monat gibt es nur aus den Zählern der Integration, und deren Statistik deckt diesen Zeitraum noch nicht ab. Einzelne Zyklen zeigen Tag, Woche und Monat für die letzten ~{n} Tage (Verlauf).",
    tk_starts: "Starts", tk_starts_day: "Starts je Tag", tk_avg_run: "Ø Laufzeit", tk_min_run: "Min. Laufzeit", tk_max_run: "Max. Laufzeit",
    tk_avg_pause: "Ø Pause", tk_max_pause: "Längste Pause", tk_short: "Zyklen < 10 min", tk_max60: "Max. Starts in 60 min",
    tk_hist_run: "Laufzeiten", tk_hist_pause: "Pausen", tk_cycles_n: "{n} Zyklen", tk_pauses_n: "{n} Pausen",
    tk_m_heating: "Heizen", tk_m_dhw: "Warmwasser", tk_m_defrost: "Abtauen", tk_m_cooling: "Kühlen", tk_m_other: "Unbekannt",
    tk_unsplit: "Zähler (nicht aufgeteilt)", tk_line: "Ø Laufzeit je Zyklus", tk_warn_day: "Takt-Schwelle überschritten",
    tk_gap: "Lücke im Verlauf", tk_axis_starts: "Starts",
    tk_begin: "Beginn", tk_dur: "Dauer", tk_pause_before: "Pause davor", tk_mode: "Betriebsart",
    tk_open_start: "Beginn nicht im Verlauf", tk_open_end: "läuft noch bzw. über das Zeitraumende", tk_cut: "Lücke im Verlauf (> 10 min) — Zyklus nicht gewertet",
    tk_day_none: "Kein Verlauf und keine Zähler-Statistik", tk_day_partial: "Verlauf deckt {p} % ab",
    c_pause: "Ø Pause", c_short: "Zyklen < 10 min",
    hint_tk_nohist: "Takt-Werte: Der Verlauf reicht nicht so weit zurück (Recorder hält ~{n} Tage, ab {since}), die Zähler der Integration gibt es erst ab {csince}.",
    hint_tk_src: "Starts und Laufzeit aus den Zählern der Integration bzw. aus dem Verlauf rekonstruiert; Pause und Anteil < 10 min nur aus dem Verlauf.",
    more_items: "+{n} weitere",
  },
  en: {
    title: "Analysis",
    view_day: "Day", view_week: "Week", view_month: "Month", view_year: "Year", view_all: "All years",
    prev: "Previous", next: "Next", today: "Today", all_years: "All years", week_short: "W",
    loading: "Loading statistics …",
    err_stats: "Could not load statistics",
    err_changes: "Settings changes are not available",
    missing_entity: "The energy counters ({id}) do not exist yet. Please update the integration and restart Home Assistant.",
    no_data_yet: "No data yet — the counters are running, the first statistics appear within an hour.",
    no_data_range: "No data in this period — the first values date from {since}.",
    history_note: "Before {since} (start of the integration's counters) the values come from the existing statistics — {sources}. These bars are not split into heating/hot water, and starts and runtime are missing there. Hatched = estimated from the average power.",
    history_note_nocounter: "The integration's counters have no statistics yet; the values come from the existing statistics — {sources}. Not split into heating/hot water, no starts and runtime. Hatched = estimated from the average power.",
    src: "Source", src_counter: "Integration counter", src_meter: "Energy meter", src_meter_shelly: "Shelly meter", src_mean: "from average power",
    unsplit: "not split", estimated: "estimated",
    only_since: "only since {since}", only_counters: "Only available since the counters started ({since}).",
    hint_estimated: "Some values come from the statistics before the integration's counters ({sources}); starts and runtime are missing there.",
    el: "Electricity", th: "Heat", az: "SPF", temp: "Outdoor temp.",
    heat: "Heating", dhw: "Hot water", rest: "Other",
    k_el: "Electricity", k_th: "Heat", k_az: "SPF", k_az_heat: "SPF heating", k_az_dhw: "SPF hot water",
    k_dhw_share: "Hot water share", k_starts: "Compressor starts", k_runtime: "Runtime",
    k_run_per_start: "Runtime per start", k_outdoor: "Avg. outdoor", k_hdd: "Heating degree days",
    k_kwh_hdd: "kWh per HDD", k_flow: "Avg. flow", k_cop: "Avg. COP (instant)",
    vs_prev: "vs. previous period (same length)", vs_prev_none: "no previous period",
    hdd_hint: "HDD: sum of (base − daily mean) over days below {base} °C",
    changes: "Settings changes", changes_none: "No settings changes recorded. Changes are derived from consecutive backups.",
    changes_more: "Show all {n}", changes_less: "Show less", in_range: "in period",
    compare: "Before / after", compare_days: "days", before: "Before", after: "After", delta: "Δ",
    close: "Close",
    c_az: "SPF", c_el_day: "Electricity per day", c_th_day: "Heat per day", c_kwh_hdd: "kWh per HDD",
    c_starts_day: "Starts per day", c_run_per_start: "Runtime per start", c_outdoor: "Avg. outdoor",
    c_flow: "Avg. flow", c_days: "Days with data",
    hint_incomplete: "The \"after\" period is still incomplete ({n} of {m} days).",
    hint_temp: "Outdoor temperature differs by {d} K — the SPF is of limited comparability. The Carnot efficiency is largely weather-independent and more meaningful; kWh per heating degree day partly compensates the consumption.",
    hint_carnot: "Carnot efficiency: achieved SPF relative to the theoretical maximum at these flow and outdoor temperatures — less weather-dependent than the SPF.",
    k_carnot: "Carnot efficiency", c_carnot: "Carnot efficiency", carnot_daily: "from daily means",
    carnot_title: "Heat ÷ (electricity × Carnot COP) from hourly values, only hours with the compressor running; COP_Carnot = (Tf+2+273.15) / ((Tf+2) − (To−6)). Less weather-dependent than the SPF.",
    carnot_daily_title: "Only daily values exist for part of the period: Carnot COP from daily means of flow and outdoor temperature (less accurate, rather too low).",
    k_standby: "Standby", standby_sub: "avg {w} W · {p} % of electricity", from_date: "from {since}",
    standby_title: "Electricity used while the compressor is off (counter \"Electrical energy standby\").",
    k_starts_h: "Starts per run hour",
    takt_title: "Warning colour above {n} starts per run hour or below {m} min runtime per start (same as the \"Short cycling\" binary sensor).",
    pp: "pp", g_energy: "Energy", g_eff: "Efficiency", g_ops: "Operation", g_weather: "Weather",
    avail_from: "Only available from {since}: {list}", avail_none: "No statistics yet: {list}",
    hint_overlap: "There were further changes in the comparison window ({n}) — the effect cannot be attributed unambiguously.",
    hint_nodata: "No daily values for this period.",
    hint_change_day: "The day of the change itself is not counted.",
    show: "Show",
    az_partial: "only times with both",
    az_partial_title: "The SPF only uses times with both electricity and heat data ({p} % of the time with electricity); implausible times (SPF < 1) are excluded.",
    az_bad: "SPF implausible (excluded)",
    az_paired: "SPF from {h} of {m} h",
    implausible_note: "An SPF below 1 is physically impossible – the flow rate was probably set too low at the time; these periods are excluded from the SPF ({from} – {to}, {n} days). Electricity and heat stay visible, the points are drawn hollow.",
    prev_incomplete: "Previous period incomplete — Δ only with at least {p} % of the data coverage",
    prev_incomplete_tile: "Previous period incomplete ({p} % coverage)",
    hint_implausible: "Days with an SPF below 1 (physically impossible, probably flow rate set too low) are excluded from the SPF.",
    reason: {
      "manuell": "Manual backup", "automatisch": "Automatic backup",
      "vor-schreibzugriff": "Before write access", "vor-wiederherstellung": "Before restore",
      "erstaufnahme": "Initial snapshot",
    },
    tk_title: "Short cycling / compressor cycles",
    tk_loading: "Loading history …",
    tk_err: "Could not load the history",
    tk_missing: "The frequency entity ({id}) is missing — compressor cycles cannot be reconstructed without it.",
    tk_no_history: "The recorder has no history of the compressor frequency.",
    tk_no_data: "There is no history left for this period (the recorder keeps ~{n} days, since {since}) and no statistics of the integration's counters (since {csince}).",
    tk_src_hist: "Reconstructed from the history (the recorder keeps ~{n} days, since {since})",
    tk_src_counter: "Starts and runtime on {n} day(s) from the integration's counters",
    tk_src_short: "reconstructed from history",
    tk_partial: "History only since {since} — older days only from the integration's counters (since {csince})",
    tk_mixed: "Min/max, pauses, classes and split only from the history",
    tk_long_hint: "Starts and runtime per period only from the integration's counters (statistics since {since}). Individual cycles: day, week or month view (history of the last ~{n} days).",
    tk_long_none: "Starts and runtime per month only come from the integration's counters, and their statistics do not cover this period yet. Individual cycles are shown in the day, week and month views for the last ~{n} days (history).",
    tk_starts: "Starts", tk_starts_day: "Starts per day", tk_avg_run: "Avg. runtime", tk_min_run: "Min. runtime", tk_max_run: "Max. runtime",
    tk_avg_pause: "Avg. pause", tk_max_pause: "Longest pause", tk_short: "Cycles < 10 min", tk_max60: "Max. starts in 60 min",
    tk_hist_run: "Runtimes", tk_hist_pause: "Pauses", tk_cycles_n: "{n} cycles", tk_pauses_n: "{n} pauses",
    tk_m_heating: "Heating", tk_m_dhw: "Hot water", tk_m_defrost: "Defrost", tk_m_cooling: "Cooling", tk_m_other: "Unknown",
    tk_unsplit: "Counter (not split)", tk_line: "Avg. runtime per cycle", tk_warn_day: "Cycling threshold exceeded",
    tk_gap: "Gap in history", tk_axis_starts: "Starts",
    tk_begin: "Start", tk_dur: "Duration", tk_pause_before: "Pause before", tk_mode: "Mode",
    tk_open_start: "Start not in history", tk_open_end: "still running or beyond the end of the period", tk_cut: "Gap in history (> 10 min) — cycle not counted",
    tk_day_none: "No history and no counter statistics", tk_day_partial: "History covers {p} %",
    c_pause: "Avg. pause", c_short: "Cycles < 10 min",
    hint_tk_nohist: "Cycling values: the history does not reach back that far (the recorder keeps ~{n} days, since {since}); the integration's counters only exist since {csince}.",
    hint_tk_src: "Starts and runtime from the integration's counters or reconstructed from the history; pause and share < 10 min only from the history.",
    more_items: "+{n} more",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Hilfsfunktionen
// ─────────────────────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const fill = (s, vars) => String(s).replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));

function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function addMonths(d, n) { const x = new Date(d); x.setDate(1); x.setMonth(x.getMonth() + n); return x; }
function startOfWeek(d) {           // Montag, wie die Wochenstatistik von HA
  const x = startOfDay(d);
  return addDays(x, -((x.getDay() + 6) % 7));
}
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y0) / DAY_MS + 1) / 7);
}
function niceMax(v, ticks = 4) {    // Achsenende, so dass jeder Teilstrich ein runder Wert ist
  if (!isNum(v) || v <= 0) return ticks * 0.25;
  const raw = v / ticks;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p * ticks;
  return 10 * p * ticks;
}
function signed(val, text) {         // "+3 %", "−3 %", "±0 %"
  if (text.replace(/[^1-9]/g, "") === "") return `±${text}`;
  return `${val >= 0 ? "+" : "−"}${text}`;
}
// Zeitpunkt, nach dem eine Statistikzeile einem Eimer zugeordnet wird: die
// Mitte des Statistikzeitraums. HA richtet Tag/Monat an der Zeitzone des
// Servers aus, die Karte rechnet in der Zeitzone des Browsers. Weichen beide
// voneinander ab (Fernzugriff aus dem Urlaub, Frontend-Option "lokale Zeit"),
// landet eine Zeile mit der Mitte trotzdem im richtigen Tag/Monat, solange der
// Versatz unter einem halben Zeitraum liegt.
function rowTime(row) {
  const s = Number(row.start), e = Number(row.end);
  return Number.isFinite(e) && e > s ? s + (e - s) / 2 : s;
}
// Eimer [start, end) im Raster der Statistik von from bis to; der letzte wird
// bei to abgeschnitten (Vorzeitraum gleicher Dauer).
function makeBuckets(period, from, to) {
  const starts = [], ends = [];
  const step = (d) => (period === "hour" ? new Date(d.getTime() + HOUR_MS) : period === "day" ? addDays(d, 1) : addMonths(d, 1));
  for (let t = new Date(from); t < to; t = step(t)) {
    starts.push(t);
    const n = step(t);
    ends.push(n < to ? n : new Date(to));
  }
  return { starts, ends };
}
function ratio(a, b, min = 0) {
  return isNum(a) && isNum(b) && b > min ? a / b : null;
}
/** Praktischer Carnot-COP (wie energy.cop_carnot); null ohne gueltige Werte. */
function copCarnot(tv, ta) {
  if (!isNum(tv) || !isNum(ta) || tv <= TEMP_SENTINEL || ta <= TEMP_SENTINEL) return null;
  const cond = tv + CARNOT_COND_K, hub = cond - (ta + CARNOT_EVAP_K);
  return hub > CARNOT_MIN_HUB_K ? (cond + 273.15) / hub : null;
}
function runtimeFactor(unit) {       // Laufzeit in Stunden
  switch (unit) {
    case "s": return 1 / 3600;
    case "min": return 1 / 60;
    case "d": return 24;
    default: return 1;
  }
}

// ── Verdichterzyklen aus dem Zustandsverlauf (v1.4.0) ───────────────────────
/** Zeile aus history/history_during_period -> {t (ms), s}; komprimierte
 *  ({s, lu, lc}) und ausfuehrliche Form (state/last_updated). */
function histEvents(rows) {
  const out = [];
  for (const r of rows || []) {
    if (!r || typeof r !== "object") continue;
    const t = r.lu !== undefined ? Number(r.lu) * 1000 : Date.parse(r.last_updated || r.last_changed || "");
    if (!Number.isFinite(t)) continue;
    out.push({ t, s: r.s !== undefined ? r.s : r.state });
  }
  return out;
}
/** Betriebsart (neue Schluessel und deutsche Zustaende bis v3.x) -> Klasse. */
function normMode(s) {
  return MODE_ALIASES[String(s ?? "").trim().toLowerCase()] || "other";
}
/**
 * Zyklen aus den Frequenz-Ereignissen fe (und Betriebsart me) in [from, to).
 * Zyklus = Frequenz von 0 auf > 0 bis zurueck auf 0. unavailable/unknown bis
 * CYCLE_GAP_MS werden ueberbrueckt (letzter Wert gilt), laengere Luecken
 * beenden einen laufenden Zyklus ("cut", nicht gewertet), danach ist der
 * Zustand unbekannt: ein laufender Verdichter ergibt einen Zyklus ohne
 * gesehenen Beginn ("openStart"). Am Ende von [from, to) offene Zyklen:
 * "openEnd". Nur vollstaendige Zyklen haben eine Dauer (dur, ms); pause = Zeit
 * seit dem Ende des vorigen gesehenen Zyklus ohne lange Luecke dazwischen.
 */
function reconstructCycles(fe, me, from, to) {
  const cycles = [], gaps = [];
  let known = null, cur = null, gapAt = null, lastEnd = null;
  const close = (t, flag) => {
    const c = { start: cur.start, end: t, openStart: cur.openStart, pause: cur.pause, cut: flag === "cut", openEnd: flag === "open" };
    c.complete = !c.openStart && !c.cut && !c.openEnd;
    c.dur = c.complete ? c.end - c.start : null;
    cycles.push(c);
    cur = null;
    lastEnd = c.cut || c.openEnd ? null : t;
  };
  for (const ev of fe || []) {
    if (ev.t >= to) break;
    const t = Math.max(ev.t, from);
    const v = parseFloat(ev.s);
    if (!Number.isFinite(v)) { if (gapAt === null) gapAt = t; continue; }
    if (gapAt !== null) {
      if (t - gapAt > CYCLE_GAP_MS) {
        gaps.push({ a: gapAt, b: t });
        if (cur) close(gapAt, "cut");
        known = null; lastEnd = null;
      }
      gapAt = null;
    }
    const run = v > 0;
    if (run && !cur) {
      const seen = known === false;
      cur = { start: t, openStart: !seen, pause: seen && lastEnd !== null ? t - lastEnd : null };
    } else if (!run && cur) close(t);
    known = run;
  }
  if (gapAt !== null && to - gapAt > CYCLE_GAP_MS) {
    gaps.push({ a: gapAt, b: to });
    if (cur) close(gapAt, "cut");
  } else if (cur) close(to, "open");
  assignModes(cycles, me || []);
  return { cycles, gaps };
}
/** Betriebsart je Zyklus: Abschnitte (segs) und ueberwiegende Art (mode). */
function assignModes(cycles, me) {
  let i = -1;                          // letzter Eintrag <= Zyklusbeginn
  for (const c of cycles) {
    while (i + 1 < me.length && me[i + 1].t <= c.start) i++;
    const segs = [], dur = {};
    let m = i >= 0 ? normMode(me[i].s) : "other", a = c.start, k = i + 1;
    while (a < c.end) {
      const b = k < me.length ? Math.min(Math.max(me[k].t, a), c.end) : c.end;
      if (b > a) {
        const last = segs[segs.length - 1];
        if (last && last.mode === m && last.b === a) last.b = b; else segs.push({ a, b, mode: m });
        dur[m] = (dur[m] || 0) + (b - a);
      }
      if (k >= me.length || b >= c.end) break;
      m = normMode(me[k].s); a = b; k++;
    }
    let best = "other", bv = 0;
    for (const x of ["heating", "dhw", "defrost", "cooling"]) if ((dur[x] || 0) > bv) { best = x; bv = dur[x]; }
    c.segs = segs; c.modeMs = dur; c.mode = best;
  }
}
/** Ueberlappung von [a, b) mit [c, d) in ms. */
function overlap(a, b, c, d) { return Math.max(0, Math.min(b, d) - Math.max(a, c)); }
/** Klasse einer Dauer (ms) in CYCLE_BINS (min). */
function binOf(ms) {
  const m = ms / 60000;
  let i = 0;
  while (i < CYCLE_BINS.length && m >= CYCLE_BINS[i]) i++;
  return i;
}

// ─────────────────────────────────────────────────────────────────────────────
// Karte
// ─────────────────────────────────────────────────────────────────────────────
class EsHeatpumpAnalysisCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = "month";
    this._anchor = new Date();
    this._hidden = new Set();
    this._data = null;
    this._loading = false;
    this._error = null;
    this._changes = null;
    this._changesError = false;
    this._showAllChanges = false;
    this._compare = null;           // {change, days, loading, result, error}
    this._compareDays = 7;
    this._since = undefined;        // Start der Zaehler der Integration (Date|null)
    this._sinceAny = null;          // erster Statistik-Zeitpunkt irgendeiner Quelle
    this._first = undefined;        // erster Statistik-Zeitpunkt je Quelle (ms|null)
    this._wsCfg = undefined;        // Antwort von es_heatpump/analysis_config
    this._tip = null;               // {index, sticky}
    this._resetHist();
    this._cyc = null;               // Ladezustand des Takt-Abschnitts {loading, error}
    this._tkTip = null;             // Tooltip im Takt-Abschnitt {id, sticky}
    this._tkOpen = true;
    try { this._tkOpen = window.localStorage?.getItem("es-heatpump-analysis-card.cycles") !== "0"; } catch (e) { /* ohne Speicher */ }
    this._width = 0;
    this._token = 0;
    this._onClick = this._onClick.bind(this);
    this._onMove = this._onMove.bind(this);
    this._onLeave = this._onLeave.bind(this);
    this.shadowRoot.addEventListener("click", this._onClick);
    this.shadowRoot.addEventListener("pointermove", this._onMove);
    this.shadowRoot.addEventListener("pointerleave", this._onLeave, true);
  }

  // ── Lovelace-Schnittstelle ───────────────────────────────────────────────
  static getStubConfig() { return {}; }

  setConfig(config) {
    const c = config || {};
    this._config = c;
    this._wsCfg = undefined;
    this._first = undefined;
    this._mergeEntities();
    const base = Number(c.heating_base_temp);
    this._base = Number.isFinite(base) ? base : 15;
    if (c.default_view && VIEWS.includes(c.default_view)) this._view = c.default_view;
    this._data = null;
    this._since = undefined;
    this._resetHist();
    if (this._hass && this.isConnected) this._reload();
    else this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    const oldLang = this._lang;
    this._hass = hass;
    this._lang = this._detectLang();
    if (first && this.isConnected) this._reload();
    else if (oldLang !== this._lang) this._render();
  }

  get hass() { return this._hass; }

  getCardSize() { return 12; }

  getGridOptions() { return { columns: "full", min_columns: 6 }; }

  connectedCallback() {
    if (!this._timer) {
      this._timer = setInterval(() => this._reload(true), REFRESH_MS);
    }
    if (!this._ro && typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver((entries) => {
        const w = Math.round(entries[0]?.contentRect?.width || 0);
        if (w && Math.abs(w - this._width) > 2) {
          this._width = w;
          this._render();
        }
      });
      this._ro.observe(this);
    }
    if (this._hass && !this._data && !this._loading) this._reload();
    else this._render();
  }

  disconnectedCallback() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
    if (this._ro) { this._ro.disconnect(); this._ro = null; }
  }

  // ── Sprache / Formatierung ───────────────────────────────────────────────
  _detectLang() {
    const l = String(this._hass?.locale?.language || this._hass?.language || "en").toLowerCase();
    return l.startsWith("de") ? "de" : "en";
  }
  _t(key, vars) {
    const s = (I18N[this._lang || "en"] || I18N.en)[key] ?? I18N.en[key] ?? key;
    return vars ? fill(s, vars) : s;
  }
  _num(v, digits = 1) {
    if (!isNum(v)) return "–";
    try {
      return new Intl.NumberFormat(this._locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
    } catch (e) { return v.toFixed(digits); }
  }
  _locale() { return this._hass?.locale?.language || this._hass?.language || "en"; }
  _date(d, opts) {
    try { return new Intl.DateTimeFormat(this._locale(), opts).format(d); } catch (e) { return d.toDateString(); }
  }
  _reason(r) {
    const map = this._t("reason");
    return (map && typeof map === "object" && map[r]) || r || "";
  }

  // ── Zeitraeume ───────────────────────────────────────────────────────────
  _range(view = this._view, anchor = this._anchor) {
    const now = new Date();
    let start, end, prevStart = null, period, buckets = [];
    switch (view) {
      case "day":
        start = startOfDay(anchor); end = addDays(start, 1); prevStart = addDays(start, -1); period = "hour";
        for (let t = new Date(start); t < end; t = new Date(t.getTime() + 3600000)) buckets.push(t);
        break;
      case "week":
        start = startOfWeek(anchor); end = addDays(start, 7); prevStart = addDays(start, -7); period = "day";
        for (let i = 0; i < 7; i++) buckets.push(addDays(start, i));
        break;
      case "year":
        start = new Date(anchor.getFullYear(), 0, 1); end = new Date(anchor.getFullYear() + 1, 0, 1);
        prevStart = new Date(anchor.getFullYear() - 1, 0, 1); period = "month";
        for (let i = 0; i < 12; i++) buckets.push(new Date(anchor.getFullYear(), i, 1));
        break;
      case "all": {
        const first = this._sinceAny || this._since;
        const firstYear = first ? first.getFullYear() : now.getFullYear();
        start = new Date(Math.min(firstYear, now.getFullYear()), 0, 1);
        end = new Date(now.getFullYear() + 1, 0, 1); period = "month";
        for (let y = start.getFullYear(); y <= now.getFullYear(); y++) buckets.push(new Date(y, 0, 1));
        break;
      }
      default: // month
        start = new Date(anchor.getFullYear(), anchor.getMonth(), 1); end = addMonths(start, 1);
        prevStart = addMonths(start, -1); period = "day";
        for (let t = new Date(start); t < end; t = addDays(t, 1)) buckets.push(t);
    }
    const ends = buckets.map((b, i) => (i + 1 < buckets.length ? buckets[i + 1] : end));
    return { view, start, end, prevStart, period, buckets, ends };
  }

  _rangeLabel(r) {
    switch (r.view) {
      case "day":
        return this._date(r.start, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
      case "week": {
        const last = addDays(r.end, -1);
        return `${this._t("week_short")} ${isoWeek(r.start)} · ${this._date(r.start, { day: "numeric", month: "short" })} – ${this._date(last, { day: "numeric", month: "short", year: "numeric" })}`;
      }
      case "year": return String(r.start.getFullYear());
      case "all": return this._t("all_years");
      default: return this._date(r.start, { month: "long", year: "numeric" });
    }
  }

  _shift(dir) {
    const a = this._anchor;
    switch (this._view) {
      case "day": this._anchor = addDays(a, dir); break;
      case "week": this._anchor = addDays(a, 7 * dir); break;
      case "year": this._anchor = new Date(a.getFullYear() + dir, a.getMonth(), 1); break;
      case "month": this._anchor = addMonths(a, dir); break;
      default: return;
    }
    this._tip = null;
    this._reload();
  }

  // ── Daten laden ──────────────────────────────────────────────────────────
  _ids(keys) {
    return [...new Set(keys.map((k) => this._entities[k]).filter(Boolean))];
  }

  /** Entity-IDs: Standard < Antwort von analysis_config < Kartenkonfiguration. */
  _mergeEntities() {
    const ws = this._wsCfg && typeof this._wsCfg === "object" ? this._wsCfg : {};
    const fromWs = {};
    const counters = ws.counters && typeof ws.counters === "object" ? ws.counters : {};
    for (const k of SUM_KEYS) if (typeof counters[k] === "string" && counters[k]) fromWs[k] = counters[k];
    for (const [k, wk] of Object.entries(WS_KEYS)) if (typeof ws[wk] === "string" && ws[wk]) fromWs[k] = ws[wk];
    const own = this._config?.entities && typeof this._config.entities === "object" ? this._config.entities : {};
    this._entities = { ...DEFAULT_ENTITIES, ...fromWs, ...own };
  }

  _stats(start, end, ids, period, types = ["change", "mean"]) {
    return this._hass.callWS({
      type: "recorder/statistics_during_period",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      statistic_ids: ids,
      period,
      types,
      // Leistung in kW: Mittel x Stunden ergibt direkt kWh
      units: { energy: "kWh", power: "kW" },
    });
  }

  async _loadAnalysisConfig() {
    try {
      const msg = { type: "es_heatpump/analysis_config" };
      if (this._config?.entry_id) msg.entry_id = this._config.entry_id;
      this._wsCfg = (await this._hass.callWS(msg)) || null;
    } catch (e) {
      // Aeltere Integration ohne den Befehl: Standard-IDs
      this._wsCfg = null;
    }
    this._mergeEntities();
  }

  /**
   * Statistik fuer [from, to): Zaehler, Stromzaehler und Mittelwerte im Raster
   * der Balken, die Leistungsmittel immer stundengenau, die
   * Aussentemperatur je Tag (Heizgradtage).
   *
   * Leistungsmittel nie aus der Tagesstatistik: Deren Mittel x 24 h rechnet
   * fehlende Stunden (HA aus, Sensor nicht verfuegbar) hoch. Bei langen
   * Zeitraeumen (Jahr, Gesamt) werden die Stundenwerte nur bis zum Ende des
   * Monats geholt, in dem beide Zaehler beginnen - danach liefern die Zaehler,
   * und die Stundenstatistik ueber Jahre waere unnoetig gross.
   *
   * Der Stromzaehler kommt (seit v4.0.1) zusaetzlich stundengenau mit: Die
   * Arbeitszahl wird nur aus Stunden gebildet, in denen Strom UND Waerme
   * vorliegen - Monatszeilen des Stromzaehlers reichen dafuer nicht, wenn die
   * Leistungsmittel erst mitten im Monat beginnen.
   *
   * Vorlauf und Aussentemperatur kommen (seit v1.3.0) ebenfalls stundengenau
   * mit (Carnot-Guetegrad aus Stundenwerten). Fuer den Rest nach dem Ende der
   * Stundenabfrage holt `daily` Tageswerte von Strom, Waerme und Vorlauf
   * (Carnot-Guetegrad aus Tagesmitteln); hourlyTo markiert die Grenze.
   */
  async _fetch(from, to, period) {
    const e = this._entities;
    const ids = this._ids([...SUM_KEYS, "meter", ...MEAN_KEYS]);
    const pIds = this._ids([...POWER_KEYS, "meter", "flow", "outdoor"]);
    let pTo = to;
    const f = this._first || {};
    if (to - from > HOURLY_MAX_DAYS * DAY_MS + 2 * HOUR_MS && this._firstOk && isNum(f.el) && isNum(f.th)) {
      const m = new Date(Math.max(f.el, f.th));
      const ende = new Date(m.getFullYear(), m.getMonth() + 1, 1);
      if (ende < pTo) pTo = ende;
    }
    const hTo = pTo > from ? pTo : from;
    const dIds = hTo < to ? this._ids(["el", "th", "meter", "flow"]) : [];
    const [stats, power, temps, daily] = await Promise.all([
      ids.length ? this._stats(from, to, ids, period) : Promise.resolve({}),
      pIds.length && pTo > from ? this._stats(from, pTo, pIds, "hour", e.meter ? ["change", "mean"] : ["mean"]) : Promise.resolve({}),
      e.outdoor ? this._stats(from, to, [e.outdoor], "day", ["mean"]) : Promise.resolve({}),
      dIds.length ? this._stats(hTo, to, dIds, "day") : Promise.resolve(null),
    ]);
    return {
      stats: stats || {},
      power: power || {},
      temps: (temps || {})[e.outdoor] || [],
      daily: daily || null,
      hourlyTo: hTo.getTime(),
    };
  }

  async _reload(silent = false) {
    if (!this._hass || !this._config) return;
    const token = ++this._token;
    if (!silent) { this._loading = true; this._error = null; this._render(); }
    try {
      if (this._wsCfg === undefined) await this._loadAnalysisConfig();
      // Beginn der Quellen; solange die Zaehler noch keine Statistik haben,
      // bei jeder Aktualisierung neu (sie entsteht erst zur vollen Stunde)
      if (this._first === undefined || (silent && !(isNum(this._first.el) && isNum(this._first.th)))) await this._loadFirsts();
      const r = this._range();
      const data = await this._fetch(r.prevStart || r.start, r.end, r.period);
      if (token !== this._token) return;
      this._data = { range: r, ...data };
      this._error = null;
    } catch (err) {
      if (token !== this._token) return;
      this._error = err?.message || err?.code || String(err);
    }
    this._loading = false;
    this._render();
    this._loadChanges(token);
    this._loadCycles(token);
  }

  /**
   * Erster Statistik-Zeitpunkt je Quelle. Monatszeilen beginnen immer am
   * Monatsersten; fuer die Zaehler der Integration wird deshalb in der
   * Stundenstatistik des ersten Monats nachgesehen - die Quellenwahl je Balken
   * braucht den Beginn auf die Stunde genau.
   */
  async _loadFirsts() {
    const keys = ["el", "th", "starts", "el_standby", "meter", "el_power", "th_power"];
    const first = {};
    let ok = true;
    try {
      const ids = this._ids(keys);
      const res = ids.length ? (await this._stats(new Date(2010, 0, 1), new Date(Date.now() + DAY_MS), ids, "month")) || {} : {};
      const at = {};
      for (const id of ids) {
        const row = (res[id] || []).find((x) => isNum(x.change) || isNum(x.mean));
        if (row) at[id] = Number(row.start);
      }
      const exact = this._ids(["el", "th", "starts", "el_standby"]).filter((id) => at[id] !== undefined);
      const byMonth = {};
      for (const id of exact) (byMonth[at[id]] = byMonth[at[id]] || []).push(id);
      for (const [m, list] of Object.entries(byMonth)) {
        const from = new Date(Number(m));
        const hres = (await this._stats(from, addDays(addMonths(from, 1), 2), list, "hour", ["change"])) || {};
        for (const id of list) {
          const row = (hres[id] || []).find((x) => isNum(x.change));
          if (row) at[id] = Number(row.start);
        }
      }
      for (const k of keys) first[k] = this._entities[k] && at[this._entities[k]] !== undefined ? at[this._entities[k]] : null;
    } catch (e) {
      ok = false;
      for (const k of keys) first[k] = null;
    }
    this._first = first;
    this._firstOk = ok;
    const cs = [first.el, first.th].filter(isNum);
    this._since = cs.length ? new Date(Math.min(...cs)) : null;
    const all = Object.values(first).filter(isNum);
    this._sinceAny = all.length ? new Date(Math.min(...all)) : this._since;
  }

  async _loadChanges(token) {
    try {
      const msg = { type: "es_heatpump/settings_changes" };
      if (this._config?.entry_id) msg.entry_id = this._config.entry_id;
      const res = await this._hass.callWS(msg);
      if (token !== this._token) return;
      const list = Array.isArray(res?.changes) ? res.changes : [];
      this._changes = list
        .map((c) => ({ ...c, _t: new Date(c.time), items: Array.isArray(c.items) ? c.items : [] }))
        .filter((c) => !Number.isNaN(c._t.getTime()))
        .sort((a, b) => a._t - b._t);
      this._changesError = false;
    } catch (e) {
      if (token !== this._token) return;
      this._changes = null;
      this._changesError = true;
    }
    this._render();
  }

  // ── Aggregation ──────────────────────────────────────────────────────────
  _runtimeFactor() {
    const st = this._hass?.states?.[this._entities.runtime];
    return runtimeFactor(st?.attributes?.unit_of_measurement);
  }

  /**
   * Deckt die Statistik des Zaehlers `key` den Eimer ab dem Zeitpunkt s ab?
   * Streng "vor": Die erste Statistikstunde ist meist nur teilweise gezaehlt
   * (Update um 13:17 -> Stunde 13:00 hat nur 43 Minuten); fuer diese Stunde
   * bzw. diesen Tag gilt deshalb noch die Ersatzquelle.
   */
  _covers(key, s) {
    if (!this._firstOk) return true;          // unbekannt: wie bis v4.0.0
    const f = this._first?.[key];
    return isNum(f) && f < s;
  }

  /**
   * Werte je Eimer mit Quelle. data: Ergebnis von _fetch; starts/ends: Date[].
   * Je Eimer: el/th (kWh) mit el_src/th_src ("counter" | "meter" | "mean"),
   * Teilzaehler nur bei "counter", starts/runtime nur bei voller Abdeckung,
   * Mittelwerte als Summe/Anzahl (<key>_s, <key>_n) und Mittel.
   *
   * Arbeitszahl (seit v4.0.1, siehe _pairAz): az_el/az_th sind Strom und
   * Waerme nur aus Teilzeitraeumen mit BEIDEN Werten und ohne unplausible
   * Tage; bad_el/bad_th der unplausible Rest. cov_<k> ist die Datenabdeckung
   * in Stunden je Quelle (fuer den Vorzeitraum-Vergleich).
   */
  _series(data, starts, ends) {
    const n = starts.length;
    const s0 = starts.map((d) => d.getTime());
    const e0 = ends.map((d) => d.getTime());
    const now = Date.now();
    const e = this._entities;
    const st = data.stats || {};
    const P = data.power || {};
    // Stunden einer Statistikzeile, beim laufenden Zeitraum bis jetzt
    const rowHours = (row) => {
      const a = Number(row.start), b = Math.min(Number(row.end), now);
      return Number.isFinite(b) && b > a ? (b - a) / HOUR_MS : 0;
    };
    const bin = (rows, f) => {
      const sum = new Array(n).fill(0), cnt = new Array(n).fill(0), hrs = new Array(n).fill(0);
      let j = 0;
      for (const row of rows || []) {
        const t = rowTime(row);
        while (j < n && t >= e0[j]) j++;
        if (j >= n) break;
        if (t < s0[j]) continue;
        const v = f(row);
        if (!isNum(v)) continue;
        sum[j] += v; cnt[j]++; hrs[j] += rowHours(row);
      }
      return { sum, cnt, hrs };
    };
    const rf = this._runtimeFactor();
    const change = (id, fac = 1) => bin(id ? st[id] : [], (r) => (isNum(r.change) ? r.change * fac : null));
    const C = {};
    for (const k of SUM_KEYS) C[k] = change(e[k], k === "runtime" ? rf : 1);
    const M = e.meter ? change(e.meter) : null;
    // Stromzaehler stundengenau (aus der Stundenabfrage), nur fuer die Abdeckung
    const MH = e.meter ? bin(P[e.meter], (r) => (isNum(r.change) ? r.change : null)) : null;
    // Stundenmittel in kW x 1 h = kWh
    const power = (id) => bin(id ? P[id] : [], (r) => (isNum(r.mean) ? Math.max(0, r.mean) : null));
    const PE = power(e.el_power), PT = power(e.th_power);
    const MEANS = {};
    for (const k of MEAN_KEYS) MEANS[k] = bin(e[k] ? st[e[k]] : [], (r) => (isNum(r.mean) ? r.mean : null));

    const bars = starts.map((_, j) => {
      const b = {};
      const cov = (k, fk = k) => this._covers(fk, s0[j]) && C[k].cnt[j] > 0;
      if (cov("el")) {
        b.el = C.el.sum[j]; b.el_src = "counter"; b.cov_el = C.el.hrs[j];
        for (const k of ["el_heat", "el_dhw"]) if (C[k].cnt[j]) b[k] = C[k].sum[j];
      } else if (M && M.cnt[j]) {
        b.el = M.sum[j]; b.el_src = "meter"; b.cov_el = MH && MH.cnt[j] ? MH.cnt[j] : M.hrs[j];
        b.el_hourly = MH ? MH.cnt[j] : 0;
      } else if (PE.cnt[j]) {
        b.el = PE.sum[j]; b.el_src = "mean"; b.cov_el = PE.cnt[j]; b.el_hourly = PE.cnt[j];
      }
      if (cov("th")) {
        b.th = C.th.sum[j]; b.th_src = "counter"; b.cov_th = C.th.hrs[j];
        for (const k of ["th_heat", "th_dhw"]) if (C[k].cnt[j]) b[k] = C[k].sum[j];
      } else if (PT.cnt[j]) {
        b.th = PT.sum[j]; b.th_src = "mean"; b.cov_th = PT.cnt[j];
      }
      if (cov("starts")) { b.starts = C.starts.sum[j]; b.cov_starts = C.starts.hrs[j]; }
      if (cov("runtime", "starts")) b.runtime = C.runtime.sum[j];
      // Standby nur aus dem eigenen Zaehler (ab v4.1.0), Anteil bezogen auf
      // den Strom desselben Eimers
      if (cov("el_standby") && isNum(b.el)) { b.el_standby = C.el_standby.sum[j]; b.cov_sb = C.el_standby.hrs[j]; }
      for (const k of MEAN_KEYS) {
        if (!MEANS[k].cnt[j]) continue;
        b[`${k}_s`] = MEANS[k].sum[j]; b[`${k}_n`] = MEANS[k].cnt[j];
        b[k] = b[`${k}_s`] / b[`${k}_n`];
        b[`cov_${k}`] = MEANS[k].hrs[j];
      }
      return b;
    });
    this._pairAz(data, bars, s0, e0);
    this._pairCarnot(data, bars, s0, e0);
    return bars;
  }

  /**
   * Carnot-Guetegrad je Eimer, waermegewichtet (siehe Kopfkommentar):
   * cn_th = Summe Waerme, cn_ec = Summe Strom x COP_Carnot, cov_carnot =
   * Stunden (bei Tageswerten 24 je Tag), cn_daily = Tage aus Tagesmitteln.
   * Stundenwerte: Strom und Waerme wie bei der Arbeitszahl (Stromzaehler, sonst
   * Leistungsmittel; Waerme aus dem Leistungsmittel), Vorlauf und
   * Aussentemperatur als Stundenmittel. Unplausible Tage (_dayCheck) und
   * unplausible ganze Eimer zaehlen nicht.
   */
  _pairCarnot(data, bars, s0, e0) {
    const n = bars.length;
    for (const b of bars) { b.cn_th = 0; b.cn_ec = 0; b.cov_carnot = 0; b.cn_daily = 0; b.carnot = null; }
    if (!n) return;
    const e = this._entities, P = data.power || {};
    const { days, meter, pe } = this._dayCheck(data);
    const means = (rows) => {
      const m = new Map();
      for (const r of rows || []) if (isNum(r.mean)) m.set(Number(r.start), r.mean);
      return m;
    };
    const add = (j, el, th, tv, ta, hours) => {
      if (!(th > 0) || !(el > 0)) return false;
      const c = copCarnot(tv, ta);
      if (c === null) return false;
      const b = bars[j];
      b.cn_th += th; b.cn_ec += el * c; b.cov_carnot += hours;
      return true;
    };
    const bucket = (t, j) => { while (j < n && t >= e0[j]) j++; return j; };
    // Stundenwerte
    const tv = means(e.flow && P[e.flow]), ta = means(e.outdoor && P[e.outdoor]);
    let j = 0;
    for (const r of (e.th_power && P[e.th_power]) || []) {
      const t = Number(r.start);
      j = bucket(t, j);
      if (j >= n) break;
      if (t < s0[j] || !isNum(r.mean) || bars[j].bad_whole) continue;
      if (days.get(startOfDay(t).getTime())?.bad) continue;
      const el = meter.has(t) ? meter.get(t) : pe.get(t);
      add(j, el, Math.max(0, r.mean), tv.get(t), ta.get(t), 1);
    }
    // Tageswerte nach dem Ende der Stundenabfrage (lange Zeitraeume)
    const D = data.daily;
    if (D) {
      const hTo = isNum(data.hourlyTo) ? data.hourlyTo : -Infinity;
      const ch = (id) => {
        const m = new Map();
        for (const r of (id && D[id]) || []) if (isNum(r.change)) m.set(Number(r.start), r.change);
        return m;
      };
      const elC = ch(e.el), thC = ch(e.th), elM = ch(e.meter);
      const tvD = means(e.flow && D[e.flow]), taD = means(data.temps);
      const starts = [...new Set([...thC.keys()])].sort((a, b) => a - b);
      j = 0;
      for (const t of starts) {
        if (t < hTo) continue;
        j = bucket(t, j);
        if (j >= n) break;
        if (t < s0[j] || bars[j].bad_whole) continue;
        if (!this._covers("th", t)) continue;
        const el = this._covers("el", t) && elC.has(t) ? elC.get(t) : elM.get(t);
        const th = thC.get(t);
        if (!isNum(el) || this._implausible(el, th, 24)) continue;
        if (add(j, el, th, tvD.get(t), taD.get(t), 24)) bars[j].cn_daily++;
      }
    }
    for (const b of bars) {
      const q = ratio(b.cn_th, b.cn_ec, MIN_EL_KWH);
      b.carnot = q === null ? null : 100 * q;
    }
  }

  /**
   * Strom und Waerme je Kalendertag aus den Stundenwerten (Stromzaehler, sonst
   * Mittel der elektrischen Leistung; Waerme aus dem Mittel der thermischen
   * Leistung), nur Stunden mit beiden Werten. Ergebnis je Datensatz einmal
   * berechnet: Map Tagesbeginn -> {el, th, h, bad}.
   */
  _dayCheck(data) {
    if (data._days) return data._days;
    const e = this._entities, P = data.power || {};
    const map = (rows, f) => {
      const m = new Map();
      for (const r of rows || []) { const v = f(r); if (isNum(v)) m.set(Number(r.start), v); }
      return m;
    };
    const meter = e.meter ? map(P[e.meter], (r) => (isNum(r.change) ? r.change : null)) : new Map();
    const pe = map(P[e.el_power], (r) => (isNum(r.mean) ? Math.max(0, r.mean) : null));
    const days = new Map();
    for (const r of (e.th_power && P[e.th_power]) || []) {
      if (!isNum(r.mean)) continue;
      const t = Number(r.start);
      const el = meter.has(t) ? meter.get(t) : pe.get(t);
      if (!isNum(el)) continue;
      const d = startOfDay(t).getTime();
      const x = days.get(d) || { el: 0, th: 0, h: 0 };
      x.el += el; x.th += Math.max(0, r.mean); x.h++;
      days.set(d, x);
    }
    for (const x of days.values()) x.bad = this._implausible(x.el, x.th, x.h);
    data._days = { days, meter, pe };
    return data._days;
  }

  /** AZ < 1 bei nennenswertem Strom (anteilig je Tag-Aequivalent) ist unmoeglich. */
  _implausible(el, th, hours) {
    return isNum(el) && isNum(th) && el >= MIN_EL_KWH && el >= IMPLAUSIBLE_EL_DAY * (hours / 24)
      && th < IMPLAUSIBLE_AZ * el;
  }

  /**
   * Arbeitszahl je Eimer nur aus Teilzeitraeumen mit Strom UND Waerme, auf der
   * feinsten verfuegbaren Ebene:
   *   - Strom aus Stromzaehler/Leistungsmittel und Waerme aus Leistungsmittel:
   *     Stunde fuer Stunde (beide Quellen liegen stundengenau vor);
   *   - sonst (Zaehler der Integration, oder keine Stundenwerte): der ganze
   *     Eimer, sofern beide Werte vorliegen - die Zaehler laufen gemeinsam.
   * Unplausible Tage (siehe _implausible) gehen nicht in az_el/az_th ein,
   * sondern in bad_el/bad_th. cov_az: Stunden mit beiden Werten.
   */
  _pairAz(data, bars, s0, e0) {
    const n = bars.length;
    if (!n) return;
    const now = Date.now();
    const { days, meter, pe } = this._dayCheck(data);
    const thRows = (this._entities.th_power && (data.power || {})[this._entities.th_power]) || [];
    const hourly = bars.map((b) => isNum(b.el) && isNum(b.th) && b.th_src === "mean" && b.el_hourly > 0);
    for (const b of bars) { b.az_el = null; b.az_th = null; b.bad_el = 0; b.bad_th = 0; b.cov_az = 0; b.cov_ok = 0; b.bad_days = 0; b.bad_from = null; b.bad_to = null; }
    const seen = bars.map(() => new Set());
    let j = 0;
    for (const r of thRows) {
      const t = Number(r.start);
      while (j < n && t >= e0[j]) j++;
      if (j >= n) break;
      if (t < s0[j] || !hourly[j] || !isNum(r.mean)) continue;
      const b = bars[j];
      const el = (b.el_src === "meter" ? meter : pe).get(t);
      if (!isNum(el)) continue;
      const th = Math.max(0, r.mean);
      const d = startOfDay(t).getTime();
      b.cov_az++;
      if (days.get(d)?.bad) {
        b.bad_el += el; b.bad_th += th;
        if (!seen[j].has(d)) {
          seen[j].add(d); b.bad_days++;
          if (b.bad_from === null || d < b.bad_from) b.bad_from = d;
          if (b.bad_to === null || d > b.bad_to) b.bad_to = d;
        }
      } else {
        b.az_el = (b.az_el || 0) + el; b.az_th = (b.az_th || 0) + th; b.cov_ok++;
      }
    }
    bars.forEach((b, i) => {
      // Stundenweise gepaart (auch: keine einzige gemeinsame Stunde)
      if (!isNum(b.el) || !isNum(b.th) || hourly[i]) return;
      // Ganzer Eimer als ein Teilzeitraum
      const end = Math.min(e0[i], now);
      const hours = Math.max(0, (end - s0[i]) / HOUR_MS);
      b.cov_az = Math.min(isNum(b.cov_el) ? b.cov_el : hours, isNum(b.cov_th) ? b.cov_th : hours);
      if (this._implausible(b.el, b.th, Math.max(1, b.cov_az))) {
        b.bad_el = b.el; b.bad_th = b.th; b.bad_whole = true;
        b.bad_days = Math.max(1, Math.round(b.cov_az / 24));
        b.bad_from = startOfDay(s0[i]).getTime(); b.bad_to = startOfDay(end - 1).getTime();
      } else { b.az_el = b.el; b.az_th = b.th; b.cov_ok = b.cov_az; }
    });
    for (const b of bars) {
      // Punkt im Diagramm erst ab nennenswertem Betrieb: reine Bereitschaft
      // (z. B. Anlage im Sommer aus) haette AZ ~0 und waere nichtssagend. In
      // die Summen der Kennzahlen gehen auch diese Stunden ein.
      const ok = isNum(b.az_el) && b.az_el >= IMPLAUSIBLE_EL_DAY * (b.cov_ok / 24);
      b.az = ok ? ratio(b.az_th, b.az_el, MIN_EL_KWH) : null;
      b.az_bad = b.bad_el > 0 ? ratio(b.bad_th, b.bad_el, MIN_EL_KWH) : null;
    }
  }

  _hdd(temps, from, to, info = null) {
    const f = from.getTime(), t = to.getTime();
    let hdd = 0, days = 0;
    for (const row of temps || []) {
      const s = rowTime(row);
      if (s < f || s >= t || !isNum(row.mean)) continue;
      days++;
      if (row.mean < this._base) hdd += this._base - row.mean;
    }
    if (info) info.cov_hdd = days;
    return days ? hdd : null;
  }

  /** Summen ueber Eimer (aus _series). */
  _sum(bars) {
    const t = { srcEl: new Set(), srcTh: new Set(), n_data: 0, n_el: 0, n_th: 0, n_starts: 0, n_runtime: 0,
      bad_days: 0, bad_from: null, bad_to: null };
    const add = (k, v) => { t[k] = (t[k] || 0) + v; };
    for (const b of bars) {
      if (isNum(b.el)) { add("el", b.el); t.n_el++; t.srcEl.add(b.el_src); }
      if (isNum(b.th)) { add("th", b.th); t.n_th++; t.srcTh.add(b.th_src); }
      if (isNum(b.el) || isNum(b.th)) t.n_data++;
      // Arbeitszahl nur aus Teilzeitraeumen mit Strom UND Waerme, ohne
      // unplausible Tage (siehe _pairAz)
      if (isNum(b.az_el) && isNum(b.az_th)) { add("az_el", b.az_el); add("az_th", b.az_th); }
      if (b.bad_el > 0) {
        add("bad_el", b.bad_el); add("bad_th", b.bad_th); t.bad_days += b.bad_days || 0;
        if (isNum(b.bad_from) && (t.bad_from === null || b.bad_from < t.bad_from)) t.bad_from = b.bad_from;
        if (isNum(b.bad_to) && (t.bad_to === null || b.bad_to > t.bad_to)) t.bad_to = b.bad_to;
      }
      // Datenabdeckung in Stunden je Quelle (Vorzeitraum-Vergleich)
      for (const k of ["el", "th", "az", "starts", "carnot", "sb", ...MEAN_KEYS]) if (isNum(b[`cov_${k}`])) add(`cov_${k}`, b[`cov_${k}`]);
      if (b.cn_ec > 0) { add("cn_th", b.cn_th); add("cn_ec", b.cn_ec); add("cn_daily", b.cn_daily || 0); }
      if (isNum(b.el_standby)) { add("sb", b.el_standby); add("sb_el", b.el); t.n_sb = (t.n_sb || 0) + 1; }
      if (b.th_src === "counter") {
        add("th_split", b.th); add("th_heat", b.th_heat || 0); add("th_dhw", b.th_dhw || 0); add("n_th_split", 1);
      }
      if (b.el_src === "counter") {
        add("el_split", b.el); add("el_heat", b.el_heat || 0); add("el_dhw", b.el_dhw || 0); add("n_el_split", 1);
      }
      if (b.el_src === "counter" && b.th_src === "counter" && !(b.bad_el > 0)) {
        add("cov_split", b.cov_az || 0);
        add("azh_el", b.el_heat || 0); add("azh_th", b.th_heat || 0);
        add("azd_el", b.el_dhw || 0); add("azd_th", b.th_dhw || 0);
      }
      if (isNum(b.starts)) { add("starts", b.starts); t.n_starts++; }
      if (isNum(b.runtime)) { add("runtime", b.runtime); t.n_runtime++; }
      for (const k of MEAN_KEYS) if (b[`${k}_n`]) { add(`${k}_s`, b[`${k}_s`]); add(`${k}_n`, b[`${k}_n`]); }
    }
    for (const k of MEAN_KEYS) if (t[`${k}_n`]) t[k] = t[`${k}_s`] / t[`${k}_n`];
    t.estimated = t.srcEl.has("mean") || t.srcTh.has("mean");
    t.historic = [...t.srcEl, ...t.srcTh].some((x) => x !== "counter");
    // Aufteilung, Starts und Laufzeit nur fuer einen Teil der Eimer mit Daten
    t.split_partial = (t.n_th_split || 0) > 0 && (t.n_th_split || 0) < t.n_th;
    t.counters_partial = t.n_starts > 0 && t.n_starts < t.n_data;
    t.counters_none = t.n_starts === 0 && t.n_data > 0;
    return t;
  }

  /** Kennzahlen fuer [from, to) im Raster period. */
  _totals(data, from, to, period) {
    const { starts, ends } = makeBuckets(period, from, to);
    const tot = this._sum(this._series(data, starts, ends));
    tot.hdd = this._hdd(data.temps, from, to, tot);
    return tot;
  }

  _kpis(tot) {
    return {
      el: tot.el, th: tot.th,
      az: ratio(tot.az_th, tot.az_el, MIN_EL_KWH),
      az_heat: ratio(tot.azh_th, tot.azh_el, MIN_EL_KWH),
      az_dhw: ratio(tot.azd_th, tot.azd_el, MIN_EL_KWH),
      dhw_share: isNum(tot.th_dhw) && isNum(tot.th_split) && tot.th_split > 0 ? (100 * tot.th_dhw) / tot.th_split : null,
      starts: tot.starts, runtime: tot.runtime,
      run_per_start: isNum(tot.runtime) && isNum(tot.starts) && tot.starts > 0 ? (60 * tot.runtime) / tot.starts : null,
      // Starts je Laufstunde erst ab 0,5 h Laufzeit (sonst Zufallswerte)
      starts_h: isNum(tot.runtime) && isNum(tot.starts) && tot.runtime >= 0.5 ? tot.starts / tot.runtime : null,
      carnot: isNum(ratio(tot.cn_th, tot.cn_ec, MIN_EL_KWH)) ? 100 * ratio(tot.cn_th, tot.cn_ec, MIN_EL_KWH) : null,
      standby: tot.n_sb ? tot.sb : null,
      standby_w: tot.n_sb && tot.cov_sb > 0 ? (1000 * tot.sb) / tot.cov_sb : null,
      standby_share: tot.n_sb && tot.sb_el > 0 ? (100 * tot.sb) / tot.sb_el : null,
      outdoor: tot.outdoor, hdd: tot.hdd,
      kwh_hdd: isNum(tot.hdd) && tot.hdd >= 1 ? ratio(tot.el, tot.hdd) : null,
      flow: tot.flow, cop: tot.cop,
    };
  }

  /** Text der Quelle fuer Tooltip und Hinweise. */
  _srcLabel(src) {
    if (src === "counter") return this._t("src_counter");
    if (src === "mean") return this._t("src_mean");
    if (src === "meter") {
      const id = this._entities.meter || "";
      const name = String(this._hass?.states?.[id]?.attributes?.friendly_name || id);
      return /shelly/i.test(name) || /shelly/i.test(id) ? this._t("src_meter_shelly") : this._t("src_meter");
    }
    return "";
  }

  _srcList(tot) {
    const parts = [];
    const el = [...tot.srcEl].filter((x) => x !== "counter").map((x) => this._srcLabel(x));
    const th = [...tot.srcTh].filter((x) => x !== "counter").map((x) => this._srcLabel(x));
    if (el.length) parts.push(`${this._t("el")}: ${el.join(" / ")}`);
    if (th.length) parts.push(`${this._t("th")}: ${th.join(" / ")}`);
    return parts.join(", ");
  }

  // ── Ereignisse ───────────────────────────────────────────────────────────
  _onClick(ev) {
    try {
      const path = ev.composedPath();
      const el = path.find((n) => n instanceof Element && n.dataset && n.dataset.action);
      if (el) {
        const a = el.dataset.action;
        if (a === "view") { this._view = el.dataset.view; this._tip = null; this._reload(); }
        else if (a === "prev") this._shift(-1);
        else if (a === "next") this._shift(1);
        else if (a === "today") { this._anchor = new Date(); this._tip = null; this._reload(); }
        else if (a === "toggle") {
          const s = el.dataset.series;
          if (this._hidden.has(s)) this._hidden.delete(s); else this._hidden.add(s);
          this._render();
        } else if (a === "change") this._openCompare(Number(el.dataset.index));
        else if (a === "compare-days") { this._compareDays = Number(el.dataset.days) || 7; if (this._compare) this._openCompare(this._compare.index); }
        else if (a === "compare-close") { this._compare = null; this._render(); }
        else if (a === "more-changes") { this._showAllChanges = !this._showAllChanges; this._render(); }
        else if (a === "drill") this._drill(Number(el.dataset.index));
        else if (a === "tk-toggle") {
          this._tkOpen = !this._tkOpen; this._tkTip = null;
          try { window.localStorage?.setItem("es-heatpump-analysis-card.cycles", this._tkOpen ? "1" : "0"); } catch (e) { /* ohne Speicher */ }
          this._render();
          if (this._tkOpen) this._loadCycles(this._token);
        }
        return;
      }
      // Takt-Abschnitt: Tippen auf Lauf/Tag haelt den Tooltip fest
      const tk = path.find((n) => n instanceof Element && n.dataset && n.dataset.tk);
      if (tk) {
        const id = tk.dataset.tk;
        this._tkTip = this._tkTip && this._tkTip.id === id && this._tkTip.sticky ? null : { id, sticky: true };
        this._updateTkTip();
        return;
      }
      if (this._tkTip?.sticky && !path.some((n) => n instanceof Element && n.classList?.contains("tk-tip"))) {
        this._tkTip = null;
        this._updateTkTip();
      }
      // Tippen auf das Diagramm: Tooltip festhalten
      const plot = path.find((n) => n instanceof Element && n.classList && n.classList.contains("plot-hit"));
      if (plot) {
        const i = this._indexAt(ev);
        if (i === null) return;
        this._tip = this._tip && this._tip.index === i && this._tip.sticky ? null : { index: i, sticky: true };
        this._updateTip();
      } else if (this._tip?.sticky && !path.some((n) => n instanceof Element && n.classList?.contains("tip"))) {
        this._tip = null;
        this._updateTip();
      }
    } catch (err) {
      console.warn("es-heatpump-analysis-card", err);
    }
  }

  _onMove(ev) {
    if (ev.pointerType !== "mouse") return;
    const path = ev.composedPath();
    const tk = path.find((n) => n instanceof Element && n.dataset && n.dataset.tk);
    if (!this._tkTip?.sticky) {
      const id = tk ? tk.dataset.tk : null;
      if (id && this._tkTip?.id !== id) { this._tkTip = { id, sticky: false }; this._updateTkTip(); }
      else if (!id && this._tkTip) { this._tkTip = null; this._updateTkTip(); }
    }
    if (tk) return;
    const marker = path.find((n) => n instanceof Element && n.dataset && n.dataset.marker !== undefined);
    if (marker) { this._showMarkerTip(Number(marker.dataset.marker)); return; }
    if (this._tip?.sticky) return;
    if (!path.some((n) => n instanceof Element && n.classList?.contains("plot-hit"))) {
      if (this._tip || this._markerTip !== undefined) { this._tip = null; this._markerTip = undefined; this._updateTip(); }
      return;
    }
    const i = this._indexAt(ev);
    if (i === null) return;
    if (this._tip?.index !== i || this._markerTip !== undefined) {
      this._markerTip = undefined;
      this._tip = { index: i, sticky: false };
      this._updateTip();
    }
  }

  _onLeave(ev) {
    if (ev.target === this.shadowRoot.querySelector(".chart") && !this._tip?.sticky) {
      this._tip = null; this._markerTip = undefined; this._updateTip();
    }
  }

  _indexAt(ev) {
    const svg = this.shadowRoot.querySelector(".chart svg");
    const g = this._geom;
    if (!svg || !g) return null;
    const rect = svg.getBoundingClientRect();
    const x = ((ev.clientX - rect.left) / rect.width) * g.w;
    const i = Math.floor((x - g.left) / g.gw);
    return i >= 0 && i < g.n ? i : null;
  }

  _drill(i) {
    const r = this._data?.range;
    if (!r || !r.buckets[i]) return;
    const next = { all: "year", year: "month", month: "day", week: "day" }[r.view];
    if (!next) return;
    this._anchor = new Date(r.buckets[i]);
    this._view = next;
    this._tip = null;
    this._reload();
  }

  // ── Verdichterzyklen: Verlauf laden und auswerten (v1.4.0) ────────────────
  /**
   * Zustandsverlauf von Frequenz und Betriebsart, je Kalendertag gecacht:
   * days: Tagesbeginn -> geladen bis (ms; < Tagesende = laufender Tag),
   * fe/me: sortierte Ereignisse, horizon: Beginn des Verlaufs (undefined =
   * noch nicht gesucht, null = kein Verlauf), ver: Zaehler fuer Memos.
   */
  _resetHist() {
    this._hist = { horizon: undefined, horizonAt: 0, days: new Map(), fe: [], me: [], ver: 0 };
    this._cycMemo = null;
  }

  _cycEnabled() {
    return this._config?.cycles !== false && !!this._entities?.frequency;
  }

  _histCall(from, to, ids) {
    return this._hass.callWS({
      type: "history/history_during_period",
      start_time: new Date(from).toISOString(),
      end_time: new Date(to).toISOString(),
      entity_ids: ids,
      minimal_response: true,
      no_attributes: true,
      significant_changes_only: false,
    });
  }

  /**
   * Beginn des Verlaufs (Recorder purge_keep_days) per Bisektion: Gibt es zu
   * einem Zeitpunkt t einen Zustand davor, liefert die Abfrage [t, t+1 s) ihn
   * als Startzustand mit Zeitstempel t. Je Probe hoechstens zwei Zeilen.
   */
  async _histHorizon() {
    const id = this._entities.frequency;
    const now = Date.now();
    const has = async (t) => {
      const ev = histEvents(((await this._histCall(t, t + 1000, [id])) || {})[id]);
      return ev.length > 0 && ev[0].t <= t + 1;
    };
    let horizon;
    if (!(await has(now - 60000))) horizon = null;
    else {
      let lo = now - HIST_PROBE_DAYS * DAY_MS, hi = now - 60000;
      if (await has(lo)) horizon = lo;
      else {
        while (hi - lo > HOUR_MS) {
          const mid = Math.round((lo + hi) / 2);
          if (await has(mid)) hi = mid; else lo = mid;
        }
        horizon = hi;
      }
    }
    this._hist.horizon = horizon;
    this._hist.horizonAt = now;
  }

  /** Tage in [from, to), deren Verlauf fehlt oder (laufender Tag) veraltet ist, als Spannen. */
  _histNeed(from, to) {
    const H = this._hist, now = Date.now();
    const spans = [];
    to = Math.min(to, now);
    for (let d = startOfDay(from); d.getTime() < to; d = addDays(d, 1)) {
      const a = d.getTime(), e = addDays(d, 1).getTime();
      if (isNum(H.horizon) && e <= H.horizon) continue;
      const got = H.days.get(a);
      if (got !== undefined && (got >= e || now - got < HIST_STALE_MS)) continue;
      const b = Math.min(e, now);
      const last = spans[spans.length - 1];
      if (last && last.b === a) last.b = b; else spans.push({ a, b });
    }
    return spans;
  }

  /** Laedt den Verlauf fuer [from, to) (nur fehlende Tage). true = es wurde geladen. */
  async _loadHist(from, to) {
    const H = this._hist;
    if (H.horizon === undefined || Date.now() - H.horizonAt > 6 * HOUR_MS) await this._histHorizon();
    if (H.horizon === null) return false;
    const spans = this._histNeed(from, to);
    if (!spans.length) return false;
    const idF = this._entities.frequency, idM = this._entities.mode;
    const ids = idM ? [idF, idM] : [idF];
    for (const { a, b } of spans) {
      const res = (await this._histCall(a, b, ids)) || {};
      const merge = (arr, rows) => {
        const keep = arr.filter((x) => x.t < a || x.t >= b);
        const add = histEvents(rows).filter((x) => x.t < b);
        return keep.concat(add).sort((x, y) => x.t - y.t);
      };
      H.fe = merge(H.fe, res[idF]);
      if (idM) H.me = merge(H.me, res[idM]);
      for (let d = startOfDay(a); d.getTime() < b; d = addDays(d, 1)) {
        const e = addDays(d, 1).getTime();
        H.days.set(d.getTime(), Math.min(e, b));
      }
    }
    H.ver++;
    return true;
  }

  /**
   * Ereignisse in [from, to). Liegt der Vortag ebenfalls im Cache, gilt der
   * letzte Wert davor als Startzustand (sonst liefert die Abfrage selbst
   * einen Startzustand zum Tagesbeginn).
   */
  _histSlice(arr, from, to) {
    let lo = 0, hi = arr.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m].t < from) lo = m + 1; else hi = m; }
    const out = [];
    if (lo > 0 && this._hist.days.has(startOfDay(from - 1).getTime())) out.push({ t: from, s: arr[lo - 1].s });
    for (let i = lo; i < arr.length && arr[i].t < to; i++) out.push(arr[i]);
    return out;
  }

  /** Zyklen in [from, to) aus dem Cache; loaded = Teilspannen mit Verlauf. */
  _reconstruct(from, to) {
    const H = this._hist;
    const now = Date.now();
    to = Math.min(to, now);
    const f0 = isNum(H.horizon) ? Math.max(from, H.horizon) : from;
    const rec = to > f0
      ? reconstructCycles(this._histSlice(H.fe, f0, to), this._histSlice(H.me, f0, to), f0, to)
      : { cycles: [], gaps: [] };
    // Abgedeckte Spannen: geladene Tage ab Beginn des Verlaufs, bis jetzt
    const loaded = [];
    for (let d = startOfDay(from); d.getTime() < to; d = addDays(d, 1)) {
      const a = Math.max(d.getTime(), f0), got = H.days.get(d.getTime());
      if (got === undefined) continue;
      const b = Math.min(got, to);
      if (b <= a) continue;
      const last = loaded[loaded.length - 1];
      if (last && last.b === a) last.b = b; else loaded.push({ a, b });
    }
    return { ...rec, loaded };
  }

  /**
   * Kennzahlen eines Tages [s, e) aus dem Verlauf: Starts (mit gesehenem
   * Beginn in [s, e)), Dauern und Pausen der vollstaendigen Zyklen, Laufzeit
   * (alle Zyklen, auf [s, e) beschnitten), max. Starts in 60 min, Abdeckung.
   */
  _histDay(rec, s, e) {
    const now = Date.now();
    const x = { starts: 0, byMode: {}, durs: [], pauses: [], runMs: 0, max60: 0, covMs: 0, gapMs: 0, cycles: [] };
    const st = [];
    for (const c of rec.cycles) {
      x.runMs += overlap(c.start, c.end, s, e);
      if (c.start < s || c.start >= e) continue;
      x.cycles.push(c);
      if (!c.openStart) { x.starts++; st.push(c.start); x.byMode[c.mode] = (x.byMode[c.mode] || 0) + 1; }
      if (c.complete) x.durs.push(c.dur);
      if (isNum(c.pause)) x.pauses.push(c.pause);
    }
    for (let i = 0, j = 0; i < st.length; i++) {
      while (st[i] - st[j] >= HOUR_MS) j++;
      x.max60 = Math.max(x.max60, i - j + 1);
    }
    for (const l of rec.loaded) x.covMs += overlap(l.a, l.b, s, e);
    for (const g of rec.gaps) x.gapMs += overlap(g.a, g.b, s, e);
    x.covMs = Math.max(0, x.covMs - x.gapMs);
    x.span = Math.max(0, Math.min(e, now) - s);       // bisher vergangene Zeit des Tages
    x.cov = x.span > 0 ? x.covMs / x.span : 0;
    return x;
  }

  /**
   * Je Tag [starts[i], ends[i]) die Quelle fuer Starts und Laufzeit: der
   * Zaehler der Integration, wo dessen Statistik den Tag abdeckt (bars[i] aus
   * _series), sonst der rekonstruierte Verlauf - nie beides addiert. Dauern,
   * Pausen und Betriebsart gibt es nur aus dem Verlauf.
   */
  _taktDays(starts, ends, bars, rec) {
    return starts.map((sd, i) => {
      const s = sd.getTime(), e = ends[i].getTime();
      const h = rec ? this._histDay(rec, s, e) : null;
      const b = bars ? bars[i] : null;
      const d = { s, e, hist: h, src: null, starts: null, runMin: 0, runN: 0, runH: null };
      if (b && isNum(b.starts)) {
        d.src = "counter"; d.starts = b.starts;
        if (isNum(b.runtime)) { d.runH = b.runtime; d.runMin = 60 * b.runtime; d.runN = b.starts; }
      } else if (h && h.covMs > 0) {
        d.src = "hist"; d.starts = h.starts; d.runH = h.runMs / HOUR_MS;
        d.runMin = h.durs.reduce((a, v) => a + v, 0) / 60000; d.runN = h.durs.length;
      }
      d.avgRun = d.runN > 0 ? d.runMin / d.runN : null;
      d.startsH = isNum(d.runH) && d.runH >= 0.5 && isNum(d.starts) ? d.starts / d.runH : null;
      // Aufteilung nach Betriebsart nur, wenn der Verlauf dieselben Starts sieht
      d.split = h && h.covMs > 0 && h.starts === d.starts ? h.byMode : null;
      d.max60 = h && h.covMs > 0 ? h.max60 : null;
      d.warn = (isNum(d.avgRun) && d.avgRun < TAKT_MIN_RUN_MIN)
        || (isNum(d.max60) ? d.max60 > TAKT_MAX_STARTS_PER_H : isNum(d.startsH) && d.startsH > TAKT_MAX_STARTS_PER_H);
      return d;
    });
  }

  /** Summen ueber Tage aus _taktDays. */
  _taktSum(days) {
    const t = { starts: 0, runMin: 0, runN: 0, runH: 0, nCounter: 0, nHist: 0, nDays: 0, durs: [], pauses: [], max60: null, gapMs: 0, covMs: 0 };
    for (const d of days) {
      if (d.src) {
        t.nDays++; t.starts += d.starts || 0; t.runMin += d.runMin; t.runN += d.runN;
        if (isNum(d.runH)) t.runH += d.runH;
        if (d.src === "counter") t.nCounter++; else t.nHist++;
      }
      if (d.hist && d.hist.covMs > 0) {
        t.durs.push(...d.hist.durs); t.pauses.push(...d.hist.pauses);
        t.max60 = Math.max(t.max60 || 0, d.hist.max60);
        t.gapMs += d.hist.gapMs; t.covMs += d.hist.covMs;
      }
    }
    const mean = (l) => (l.length ? l.reduce((a, v) => a + v, 0) / l.length : null);
    t.has = t.nDays > 0;
    t.avgRun = t.runN > 0 ? t.runMin / t.runN : null;
    t.minRun = t.durs.length ? Math.min(...t.durs) / 60000 : null;
    t.maxRun = t.durs.length ? Math.max(...t.durs) / 60000 : null;
    t.avgPause = t.pauses.length ? mean(t.pauses) / 60000 : null;
    t.maxPause = t.pauses.length ? Math.max(...t.pauses) / 60000 : null;
    t.startsH = t.has && t.runH >= 0.5 ? t.starts / t.runH : null;
    t.short = t.durs.length ? (100 * t.durs.filter((v) => v < TAKT_MIN_RUN_MIN * 60000).length) / t.durs.length : null;
    t.startsDay = t.nDays ? t.starts / t.nDays : null;
    return t;
  }

  /** Auswertung fuer den angezeigten Zeitraum (Tag/Woche/Monat), gememot. */
  _cycleView() {
    const r = this._data?.range;
    if (!r || !CYCLE_VIEWS.includes(r.view)) return null;
    const key = `${r.view}|${r.start.getTime()}|${this._hist.ver}|${this._bars?.length}|${Math.floor(Date.now() / 60000)}`;
    if (this._cycMemo?.key === key && this._cycMemo.bars === this._bars) return this._cycMemo.out;
    // Ein Tag Vorlauf (Pause vor dem ersten Lauf, Lauf ueber Mitternacht) und
    // ein Tag Nachlauf (Ende eines Laufs ueber das Zeitraumende hinaus)
    const rec = this._reconstruct(addDays(r.start, -1).getTime(), addDays(r.end, 1).getTime());
    let starts, ends, bars = null;
    if (r.view === "day") {
      starts = [r.start]; ends = [r.end];
      // Stundenbalken zum Tag zusammenfassen (nur bei voller Zaehler-Abdeckung)
      const hb = this._bars || [];
      if (hb.some((b) => isNum(b.starts)) && this._covers("starts", r.start.getTime())) {
        bars = [{ starts: hb.reduce((a, b) => a + (b.starts || 0), 0), runtime: hb.reduce((a, b) => a + (b.runtime || 0), 0) }];
      }
    } else { starts = r.buckets; ends = r.ends; bars = this._bars || null; }
    const days = this._taktDays(starts, ends, bars, rec);
    const out = { rec, days, sum: this._taktSum(days), from: r.start.getTime(), to: r.end.getTime() };
    this._cycMemo = { key, out, bars: this._bars };
    return out;
  }

  async _loadCycles(token) {
    const r = this._data?.range;
    if (!r || !CYCLE_VIEWS.includes(r.view) || !this._cycEnabled() || !this._tkOpen || !this._hass) return;
    const from = addDays(r.start, -1).getTime(), to = addDays(r.end, 1).getTime();
    const needH = this._hist.horizon === undefined || Date.now() - this._hist.horizonAt > 6 * HOUR_MS;
    if (!needH && !this._histNeed(from, to).length) return;
    const showSpin = !this._cyc || this._cyc.error || needH || this._histNeed(from, to).some((x) => !this._hist.days.has(x.a));
    if (showSpin) { this._cyc = { loading: true }; this._render(); }
    try {
      await this._loadHist(from, to);
      if (token !== this._token) return;
      this._cyc = { loading: false };
    } catch (err) {
      if (token !== this._token) return;
      this._cyc = { loading: false, error: err?.message || err?.code || String(err) };
    }
    this._render();
  }

  // ── Vorher/Nachher ───────────────────────────────────────────────────────
  async _openCompare(index) {
    const change = this._changes?.[index];
    if (!change) return;
    const days = this._compareDays;
    const token = (this._cmpToken = (this._cmpToken || 0) + 1);
    this._compare = { index, change, days, loading: true };
    this._render();
    this.shadowRoot.querySelector(".compare")?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    try {
      const day0 = startOfDay(change._t);
      const bStart = addDays(day0, -days), bEnd = day0;
      const aStart = addDays(day0, 1), aEnd = addDays(aStart, days);
      // Dieselbe Quellenwahl wie im Diagramm, je Tag
      const data = await this._fetch(bStart, aEnd, "day");
      if (token !== this._cmpToken) return;
      // Verdichterzyklen aus dem Verlauf, soweit er reicht (Cache wie der Takt-Abschnitt)
      let rec = null;
      if (this._cycEnabled()) {
        try {
          await this._loadHist(addDays(bStart, -1).getTime(), addDays(aEnd, 1).getTime());
          if (token !== this._cmpToken) return;
          if (this._hist.horizon !== null) rec = this._reconstruct(addDays(bStart, -1).getTime(), addDays(aEnd, 1).getTime());
        } catch (e) { rec = null; }
      }
      const now = Date.now();
      // Nur vollstaendige Tage: der laufende Tag zaehlt nicht
      const temps = data.temps.filter((row) => Number(row.end) <= now);
      const side = (from, to) => {
        const { starts, ends } = makeBuckets("day", from, to);
        const full = starts.map((st, i) => [st, ends[i]]).filter(([, en]) => en.getTime() <= now);
        const fs = full.map((x) => x[0]), fe = full.map((x) => x[1]);
        const bars = this._series(data, fs, fe);
        const tot = this._sum(bars);
        tot.hdd = this._hdd(temps, from, to, tot);
        // Takt-Werte je Tag: Zaehler, sonst nur weitgehend abgedeckte Tage aus dem Verlauf
        const tdays = this._taktDays(fs, fe, bars, rec).map((d) => (
          d.src === "hist" && d.hist.cov < HIST_DAY_COV ? { ...d, src: null, hist: null } : d.src === "counter" && d.hist && d.hist.cov < HIST_DAY_COV ? { ...d, hist: null } : d));
        return { tot, days: tot.n_data, takt: this._taktSum(tdays) };
      };
      const before = side(bStart, bEnd);
      const after = side(aStart, aEnd);
      const fullAfterDays = Math.max(0, Math.min(days, Math.floor((now - aStart.getTime()) / DAY_MS)));
      const others = (this._changes || []).filter((c) => c !== change && c._t >= bStart && c._t < aEnd).length;
      this._compare = { index, change, days, loading: false, before, after, incomplete: fullAfterDays < days, fullAfterDays, others };
    } catch (err) {
      if (token !== this._cmpToken) return;
      this._compare = { index, change, days, loading: false, error: err?.message || String(err) };
    }
    this._render();
  }

  // ── Darstellung ──────────────────────────────────────────────────────────
  _render() {
    if (!this.shadowRoot) return;
    try {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${this._renderBody()}</ha-card>`;
      // Diagramm einmal auf die tatsaechliche Breite nachziehen (Text nicht verzerren)
      const cw = this.shadowRoot.querySelector(".chart")?.clientWidth || 0;
      if (cw >= 280 && this._geom && Math.abs(cw - this._geom.w) > 2 && !this._again) {
        this._chartW = cw;
        this._again = true;
        try { this._render(); } finally { this._again = false; }
        return;
      }
      this._updateTip();
      this._updateTkTip();
    } catch (err) {
      console.error("es-heatpump-analysis-card", err);
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="msg err">ES Heatpump: ${esc(err?.message || err)}</div></ha-card>`;
    }
  }

  _renderBody() {
    const title = this._config?.title ?? this._t("title");
    const r = this._range();
    const isNow = new Date() >= r.start && new Date() < r.end;
    const canNext = r.view !== "all" && r.end <= new Date() ? true : false;
    const tabs = VIEWS.map((v) => `<button class="tab ${v === this._view ? "on" : ""}" data-action="view" data-view="${v}">${esc(this._t(`view_${v}`))}</button>`).join("");
    const nav = this._view === "all" ? `<span class="rlabel">${esc(this._rangeLabel(r))}</span>` : `
      <button class="icon" data-action="prev" title="${esc(this._t("prev"))}" aria-label="${esc(this._t("prev"))}">‹</button>
      <span class="rlabel">${esc(this._rangeLabel(r))}</span>
      <button class="icon" data-action="next" ${canNext ? "" : "disabled"} title="${esc(this._t("next"))}" aria-label="${esc(this._t("next"))}">›</button>
      ${isNow ? "" : `<button class="link" data-action="today">${esc(this._t("today"))}</button>`}`;
    let main;
    if (!this._hass) main = `<div class="msg">${esc(this._t("loading"))}</div>`;
    else if (this._error) main = `<div class="msg err">${esc(this._t("err_stats"))}: ${esc(this._error)}</div>`;
    else if (!this._data) main = `<div class="msg">${esc(this._t("loading"))}</div>`;
    else main = this._renderMain();
    return `
      ${title || this._loading ? `<div class="head"><div class="title">${esc(title || "")}</div>${this._loading ? `<div class="spin" aria-label="${esc(this._t("loading"))}"></div>` : ""}</div>` : ""}
      <div class="tabs" role="tablist">${tabs}</div>
      <div class="nav">${nav}</div>
      ${main}
      ${this._data && !this._error ? this._renderCycles() : ""}
      ${this._renderCompare()}
      ${this._renderChanges()}`;
  }

  _renderMain() {
    const r = this._data.range;
    const now = new Date();
    const bars = this._series(this._data, r.buckets, r.ends);
    const hasAny = bars.some((b) => isNum(b.el) || isNum(b.th));
    const dateOpts = { day: "numeric", month: "short", year: "numeric" };
    // Kennzahlen: aktueller Zeitraum bis jetzt vs. Vorzeitraum gleicher Laenge
    const curEnd = r.end > now ? now : r.end;
    const curTot = this._sum(bars);
    curTot.hdd = this._hdd(this._data.temps, r.start, r.end, curTot);
    const cur = this._kpis(curTot);
    let prev = null, prevTot = null;
    if (r.prevStart) {
      const prevEnd = new Date(Math.min(r.start.getTime(), r.prevStart.getTime() + (curEnd - r.start)));
      prevTot = this._totals(this._data, r.prevStart, prevEnd, r.period);
      prev = this._kpis(prevTot);
    }
    let notice = "";
    if (!hasAny) {
      const any = this._sinceAny || this._since;
      if (!any && !this._hass.states[this._entities.el] && !this._hass.states[this._entities.th]) {
        this._bars = bars;
        this._geom = null;
        return `<div class="msg info">${esc(this._t("missing_entity", { id: this._entities.el }))}</div>`;
      }
      // "Noch keine Daten" nur, wenn wirklich keine Quelle Statistik hat
      notice = any ? this._t("no_data_range", { since: this._date(any, dateOpts) }) : this._t("no_data_yet");
    } else if (curTot.historic) {
      const sources = this._srcList(curTot);
      notice = this._since
        ? this._t("history_note", { since: this._date(this._since, dateOpts), sources })
        : this._t("history_note_nocounter", { sources });
    }
    this._bars = bars;
    // Unplausible Arbeitszahl (AZ < 1) im angezeigten Zeitraum
    let bad = "";
    if (curTot.bad_days > 0 && isNum(curTot.bad_from)) {
      bad = this._t("implausible_note", {
        from: this._date(new Date(curTot.bad_from), dateOpts), to: this._date(new Date(curTot.bad_to), dateOpts), n: curTot.bad_days,
      });
    }
    return `
      ${notice ? `<div class="msg info">${esc(notice)}</div>` : ""}
      ${this._renderLegend(bars)}
      <div class="chart">${this._renderChart(r, bars)}<div class="tip" hidden></div></div>
      ${bad ? `<div class="msg warn">${esc(bad)}</div>` : ""}
      ${this._renderKpis(cur, prev, curTot, prevTot)}`;
  }

  _renderLegend(bars = []) {
    const items = [
      ["el", this._t("el"), "c-elh"], ["th", this._t("th"), "c-thh"],
      ["az", this._t("az"), "c-az"], ["temp", this._t("temp"), "c-temp"],
    ];
    const split = bars.some((b) => b.el_src === "counter" || b.th_src === "counter");
    const unsplit = bars.some((b) => (isNum(b.el) && b.el_src !== "counter") || (isNum(b.th) && b.th_src !== "counter"));
    const est = bars.some((b) => b.el_src === "mean" || b.th_src === "mean");
    let sub = "";
    if (split || !unsplit) sub += `<i class="sw c-elh"></i>${esc(this._t("heat"))} <i class="sw c-eld"></i>${esc(this._t("dhw"))} <i class="sw c-elr"></i>${esc(this._t("rest"))}`;
    if (unsplit) sub += ` <i class="sw c-elu"></i><i class="sw c-thu"></i>${esc(this._t("unsplit"))}`;
    if (est) sub += ` <i class="sw hatch"></i>${esc(this._t("estimated"))}`;
    return `<div class="legend">${items.map(([k, label, cls]) => `<button class="chip ${this._hidden.has(k) ? "off" : ""}" data-action="toggle" data-series="${k}" aria-pressed="${!this._hidden.has(k)}"><i class="sw ${cls} ${k === "az" || k === "temp" ? "line" : ""}"></i>${esc(label)}</button>`).join("")}<span class="sub">${sub}</span></div>`;
  }

  _renderChart(r, bars) {
    const w = Math.max(280, this._chartW || this._width || this.clientWidth || 600);
    const narrow = w < 480;
    const h = narrow ? 210 : 250;
    const left = 40, right = 34, top = 16, bottom = 22;
    const pw = w - left - right, ph = h - top - bottom;
    const n = r.buckets.length;
    const gw = pw / n;
    this._geom = { w, h, left, right, top, bottom, pw, ph, n, gw };
    const showEl = !this._hidden.has("el"), showTh = !this._hidden.has("th");
    const showAz = !this._hidden.has("az"), showTemp = !this._hidden.has("temp");

    // Je Balken: Stapel [Wert, Klasse]; ohne Zaehler der Integration ein
    // einziger Block "nicht aufgeteilt", geschaetzte Werte schraffiert.
    const stack = (b, k) => {
      const tot = isNum(b[k]) ? b[k] : 0;
      if (b[`${k}_src`] !== "counter") return [[tot, `c-${k}u`]];
      const h = isNum(b[`${k}_heat`]) ? b[`${k}_heat`] : 0, d = isNum(b[`${k}_dhw`]) ? b[`${k}_dhw`] : 0;
      return [[h, `c-${k}h`], [d, `c-${k}d`], [Math.max(0, tot - h - d), `c-${k}r`]];
    };
    const parts = bars.map((b) => ({
      el: stack(b, "el"), elT: isNum(b.el) ? b.el : 0, elEst: b.el_src === "mean",
      th: stack(b, "th"), thT: isNum(b.th) ? b.th : 0, thEst: b.th_src === "mean",
      az: isNum(b.az) ? b.az : null,
      // nur unplausible Teilzeitraeume: hohler Punkt ohne Linie
      azBad: !isNum(b.az) && isNum(b.az_bad) ? b.az_bad : null,
      temp: isNum(b.outdoor) ? b.outdoor : null,
    }));
    const maxY = niceMax(Math.max(0, ...parts.map((p) => Math.max(showEl ? p.elT : 0, showTh ? p.thT : 0))));
    const y = (v) => top + ph - (v / maxY) * ph;
    const azMax = Math.min(AZ_AXIS_MAX, Math.max(4, Math.ceil(Math.max(0, ...parts.map((p) => p.az || 0)))));
    const yAz = (v) => top + ph - (Math.min(v, azMax) / azMax) * ph;
    const temps = parts.map((p) => p.temp).filter(isNum);
    let tMin = temps.length ? Math.floor(Math.min(...temps)) - 2 : 0, tMax = temps.length ? Math.ceil(Math.max(...temps)) + 2 : 10;
    if (tMax - tMin < 6) { const m = (tMax + tMin) / 2; tMin = m - 3; tMax = m + 3; }
    const yT = (v) => top + ph - ((v - tMin) / (tMax - tMin)) * ph;

    let s = "";
    // Gitter und Achsen
    for (let i = 0; i <= 4; i++) {
      const v = (maxY / 4) * i, yy = y(v);
      s += `<line class="grid" x1="${left}" x2="${left + pw}" y1="${yy}" y2="${yy}"/>`;
      s += `<text class="ax" x="${left - 5}" y="${yy + 3}" text-anchor="end">${this._num(v, maxY < 4 ? (maxY < 2 ? 2 : 1) : 0)}</text>`;
      if (showAz) s += `<text class="ax az" x="${left + pw + 5}" y="${y(v) + 3}">${this._num((azMax / 4) * i, azMax < 4 ? 1 : 0)}</text>`;
    }
    s += `<text class="ax unit" x="${left - 5}" y="${top - 5}" text-anchor="end">kWh</text>`;
    if (showAz) s += `<text class="ax az unit" x="${left + pw + 5}" y="${top - 5}">AZ</text>`;
    if (showTemp && temps.length) {
      s += `<text class="ax temp" x="${left + pw - 3}" y="${top + 9}" text-anchor="end">${this._num(tMax, 0)} °C</text>`;
      s += `<text class="ax temp" x="${left + pw - 3}" y="${top + ph - 3}" text-anchor="end">${this._num(tMin, 0)} °C</text>`;
    }
    // Balken
    const both = showEl && showTh;
    const bw = Math.max(1.5, Math.min(28, (both ? gw * 0.36 : gw * 0.6)));
    s += `<defs><pattern id="esa-hatch" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)"><rect class="hatch-line" x="0" y="0" width="2" height="5"/></pattern></defs>`;
    parts.forEach((p, i) => {
      const cx = left + gw * (i + 0.5);
      const stacks = [];
      if (showEl) stacks.push(["el", both ? cx - bw - 1 : cx - bw / 2]);
      if (showTh) stacks.push(["th", both ? cx + 1 : cx - bw / 2]);
      for (const [k, x] of stacks) {
        let acc = 0;
        const est = p[`${k}Est`];
        p[k].forEach(([v, klass]) => {
          if (!(v > 0)) return;
          const y1 = y(acc + v), y0 = y(acc);
          const geo = `x="${x.toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0.5, y0 - y1).toFixed(1)}" rx="1"`;
          s += `<rect class="${klass}${est ? " est" : ""}" ${geo}/>`;
          if (est) s += `<rect class="hatch" ${geo}/>`;
          acc += v;
        });
      }
    });
    // Linien: Aussentemperatur und Arbeitszahl
    const line = (vals, fy, klass) => {
      let d = "", dots = "", pen = false;
      vals.forEach((v, i) => {
        const cx = left + gw * (i + 0.5);
        if (!isNum(v)) { pen = false; return; }
        const yy = fy(v).toFixed(1);
        d += `${pen ? "L" : "M"}${cx.toFixed(1)} ${yy}`;
        pen = true;
        if (n <= 40) dots += `<circle class="${klass}" cx="${cx.toFixed(1)}" cy="${yy}" r="${n <= 14 ? 3 : 2}"/>`;
      });
      return d ? `<path class="${klass} ln" d="${d}"/>${dots}` : "";
    };
    if (showTemp) s += line(parts.map((p) => p.temp), yT, "c-temp");
    if (showAz) {
      s += line(parts.map((p) => p.az), yAz, "c-az");
      parts.forEach((p, i) => {
        if (!isNum(p.azBad)) return;
        const cx = left + gw * (i + 0.5);
        s += `<circle class="c-az bad" cx="${cx.toFixed(1)}" cy="${yAz(p.azBad).toFixed(1)}" r="${n <= 14 ? 3.5 : 2.5}"/>`;
      });
    }
    // X-Beschriftung
    const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / (r.view === "week" ? (narrow ? 22 : 44) : 30)))));
    r.buckets.forEach((b, i) => {
      if (i % step !== 0) return;
      const cx = left + gw * (i + 0.5);
      s += `<text class="ax" x="${cx.toFixed(1)}" y="${h - 6}" text-anchor="middle">${esc(this._xLabel(r.view, b, narrow))}</text>`;
    });
    // Jetzt-Linie
    const now = Date.now();
    if (now > r.start.getTime() && now < r.end.getTime()) {
      const xn = this._xOf(r, now);
      if (xn !== null) s += `<line class="now" x1="${xn}" x2="${xn}" y1="${top}" y2="${top + ph}"/>`;
    }
    // Trefferflaeche fuer Tooltips
    s += `<rect class="plot-hit" x="${left}" y="${top}" width="${pw}" height="${ph}"/>`;
    // Markierungen der Einstellungsaenderungen (oben drueber, damit sie anklickbar bleiben)
    (this._changes || []).forEach((c, idx) => {
      const t = c._t.getTime();
      if (t < r.start.getTime() || t >= r.end.getTime()) return;
      const x = this._xOf(r, t);
      if (x === null) return;
      s += `<g class="marker" data-marker="${idx}" data-action="change" data-index="${idx}" role="button" tabindex="0">
        <line x1="${x}" x2="${x}" y1="${top}" y2="${top + ph}"/>
        <path d="M${x - 5} ${top - 9}h10l-5 7z"/>
        <rect class="mhit" x="${x - 7}" y="${top - 12}" width="14" height="${ph + 12}"/>
      </g>`;
    });
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" role="img" aria-label="${esc(this._t("title"))}">${s}</svg>`;
  }

  _xOf(r, t) {
    const g = this._geom;
    for (let i = 0; i < r.buckets.length; i++) {
      const s = r.buckets[i].getTime(), e = r.ends[i].getTime();
      if (t >= s && t < e) return +(g.left + g.gw * (i + (t - s) / (e - s))).toFixed(1);
    }
    return null;
  }

  _xLabel(view, d, narrow) {
    switch (view) {
      case "day": return String(d.getHours()).padStart(2, "0");
      case "week": return this._date(d, narrow ? { weekday: "narrow" } : { weekday: "short", day: "numeric" });
      case "month": return String(d.getDate());
      case "year": return this._date(d, { month: narrow ? "narrow" : "short" });
      default: return String(d.getFullYear());
    }
  }

  _bucketLabel(view, d) {
    switch (view) {
      case "day": return `${this._date(d, { weekday: "short", day: "numeric", month: "short" })}, ${String(d.getHours()).padStart(2, "0")}:00–${String((d.getHours() + 1) % 24).padStart(2, "0")}:00`;
      case "week": case "month": return this._date(d, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
      case "year": return this._date(d, { month: "long", year: "numeric" });
      default: return String(d.getFullYear());
    }
  }

  _updateTip() {
    const tip = this.shadowRoot.querySelector(".tip");
    if (!tip) return;
    const g = this._geom, r = this._data?.range;
    if (this._markerTip !== undefined && this._changes?.[this._markerTip] && r) {
      const c = this._changes[this._markerTip];
      const x = this._xOf(r, c._t.getTime());
      tip.innerHTML = this._changeTipHtml(c);
      this._placeTip(tip, x);
      return;
    }
    if (!this._tip || !g || !r || !this._bars?.[this._tip.index]) { tip.hidden = true; return; }
    const i = this._tip.index, b = this._bars[i];
    const az = isNum(b.az) ? b.az : null;
    const row = (label, v, unit, d = 1, cls = "") => (isNum(v) ? `<tr><td>${cls ? `<i class="sw ${cls}"></i>` : ""}${esc(label)}</td><td>${this._num(v, d)}${unit ? ` ${unit}` : ""}</td></tr>` : "");
    const srcRow = (k) => (isNum(b[k]) ? `<tr class="src"><td>${esc(this._t("src"))} ${esc(this._t(k))}</td><td>${esc(this._srcLabel(b[`${k}_src`]))}</td></tr>` : "");
    const pre = (k) => (b[`${k}_src`] === "mean" ? "≈ " : "");
    const canDrill = { all: 1, year: 1, month: 1, week: 1 }[r.view];
    tip.innerHTML = `<div class="tt">${esc(this._bucketLabel(r.view, r.buckets[i]))}</div><table>
      ${row(`${this._t("el")} ${this._t("heat")}`, b.el_heat, "kWh", 2, "c-elh")}
      ${row(`${this._t("el")} ${this._t("dhw")}`, b.el_dhw, "kWh", 2, "c-eld")}
      ${row(`${pre("el")}${this._t("el")}`, b.el, "kWh", 2, b.el_src === "counter" ? "" : "c-elu")}
      ${row(`${this._t("th")} ${this._t("heat")}`, b.th_heat, "kWh", 2, "c-thh")}
      ${row(`${this._t("th")} ${this._t("dhw")}`, b.th_dhw, "kWh", 2, "c-thd")}
      ${row(`${pre("th")}${this._t("th")}`, b.th, "kWh", 2, b.th_src === "counter" ? "" : "c-thu")}
      ${row(this._t("az"), az, "", 2, "c-az")}
      ${row(this._t("k_carnot") + (b.cn_daily > 0 ? ` (${this._t("carnot_daily")})` : ""), b.carnot, "%", 0)}
      ${b.bad_el > 0 ? row(this._t("az_bad"), isNum(b.az_bad) ? b.az_bad : 0, "", 2) : ""}
      ${row(this._t("temp"), b.outdoor, "°C", 1, "c-temp")}
      ${row(this._t("k_starts"), b.starts, "", 0)}
      ${row(this._t("k_runtime"), b.runtime, "h", 1)}
      ${row(this._t("k_standby"), b.el_standby, "kWh", 2)}
      ${srcRow("el")}${srcRow("th")}
      ${this._pairedRow(b)}
    </table>${b.bad_el > 0 ? `<div class="dim warnt">${esc(this._t("hint_implausible"))}</div>` : ""}${this._tip.sticky && canDrill ? `<button class="link" data-action="drill" data-index="${i}">${esc(this._t("show"))} ›</button>` : ""}`;
    this._placeTip(tip, g.left + g.gw * (i + 0.5));
  }

  /** Tooltip-Zeile: Arbeitszahl nur aus einem Teil der Stunden gebildet. */
  _pairedRow(b) {
    if (!isNum(b.el) || !isNum(b.th) || !(b.cov_az > 0)) return "";
    const m = Math.max(b.cov_el || 0, b.cov_th || 0);
    if (!(m > 0) || b.cov_az >= 0.98 * m) return "";
    return `<tr class="src"><td colspan="2">${esc(this._t("az_paired", { h: this._num(b.cov_az, 0), m: this._num(m, 0) }))}</td></tr>`;
  }

  _changeTipHtml(c) {
    const items = c.items.slice(0, 6).map((it) => `<li>${esc(this._itemText(it))}</li>`).join("");
    const more = c.items.length > 6 ? `<li class="dim">${esc(this._t("more_items", { n: c.items.length - 6 }))}</li>` : "";
    return `<div class="tt">${esc(this._date(c._t, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))}</div>
      <div class="dim">${esc(this._reason(c.reason))}</div><ul>${items}${more}</ul>`;
  }

  _placeTip(tip, x) {
    const g = this._geom;
    if (!g || x === null || x === undefined) { tip.hidden = true; return; }
    tip.hidden = false;
    const chart = this.shadowRoot.querySelector(".chart");
    const cw = chart?.clientWidth || g.w;
    const px = (x / g.w) * cw;
    const tw = tip.offsetWidth || 200;
    let lx = px + 12;
    if (lx + tw > cw) lx = Math.max(0, px - tw - 12);
    tip.style.left = `${lx}px`;
    tip.style.top = `${g.top}px`;
    tip.classList.toggle("sticky", !!this._tip?.sticky);
  }

  _showMarkerTip(idx) {
    if (this._markerTip === idx) return;
    this._markerTip = idx;
    this._updateTip();
  }

  _itemText(it) {
    if (it && it.text) return String(it.text);
    const name = it?.name || it?.par || "?";
    return `${name}: ${it?.old ?? "–"} → ${it?.new ?? "–"}`;
  }

  /**
   * Reicht die Datenabdeckung des Vorzeitraums fuer ein Delta der Kennzahl k?
   * Abdeckung = Stunden (Heizgradtage: Tage) mit Daten der jeweiligen Quelle;
   * der Vorzeitraum braucht mindestens PREV_COVERAGE_MIN davon im Vergleich
   * zum aktuellen Zeitraum. Liefert null (ok), sonst den Anteil in %.
   */
  _prevCoverage(k, tot, prevTot) {
    if (!tot || !prevTot) return null;
    const keys = {
      el: ["el"], th: ["th"], az: ["az"], az_heat: ["split"], az_dhw: ["split"], dhw_share: ["split"],
      starts: ["starts"], runtime: ["starts"], run_per_start: ["starts"], starts_h: ["starts"],
      carnot: ["carnot"], standby: ["sb"],
      outdoor: ["outdoor"], hdd: ["hdd"], kwh_hdd: ["el", "hdd"], flow: ["flow"], cop: ["cop"],
    }[k];
    if (!keys) return null;
    let worst = null;
    for (const c of keys) {
      const a = tot[`cov_${c}`], p = prevTot[`cov_${c}`];
      if (!isNum(a) || a <= 0) continue;
      const q = isNum(p) ? p / a : 0;
      if (q < PREV_COVERAGE_MIN && (worst === null || q < worst)) worst = q;
    }
    return worst === null ? null : Math.round(100 * worst);
  }

  /**
   * Deckt die Statistik des Standby-Zaehlers den ganzen Zeitraum ab?
   * Liefert {ok} oder {from: ms|null} (Beginn der Statistik, null = keine).
   */
  _standbyCoverage(r) {
    if (!this._firstOk) return { ok: true };
    const f = this._first?.el_standby;
    if (isNum(f) && f < r.start.getTime()) return { ok: true };
    return { ok: false, from: isNum(f) ? f : null };
  }

  _renderKpis(cur, prev, tot = null, prevTot = null) {
    const r = this._data?.range;
    const now = Date.now();
    const dateLong = { day: "numeric", month: "short", year: "numeric" };
    // Gruppen; je Kachel [Schluessel, Label, Einheit, Nachkommastellen,
    // Richtung (+1 hoeher besser, -1 niedriger besser, 0 neutral), Delta absolut (K)?]
    const groups = [
      ["g_energy", [["el", "k_el", "kWh", 1, -1], ["th", "k_th", "kWh", 1, 0],
        ["dhw_share", "k_dhw_share", "%", 0, 0], ["standby", "k_standby", "kWh", 1, -1]]],
      ["g_eff", [["az", "k_az", "", 2, 1], ["carnot", "k_carnot", "%", 0, 1, "pp"],
        ["az_heat", "k_az_heat", "", 2, 1], ["az_dhw", "k_az_dhw", "", 2, 1],
        ["kwh_hdd", "k_kwh_hdd", "kWh/Kd", 2, -1]]],
      ["g_ops", [["starts", "k_starts", "", 0, -1], ["runtime", "k_runtime", "h", 1, 0],
        ["run_per_start", "k_run_per_start", "min", 0, 1], ["starts_h", "k_starts_h", "/h", 1, -1],
        ["flow", "k_flow", "°C", 1, 0, true]]],
      ["g_weather", [["outdoor", "k_outdoor", "°C", 1, 0, true], ["hdd", "k_hdd", "Kd", 0, 0]]],
    ];
    if (!isNum(cur.az) && isNum(cur.cop)) groups[1][1].push(["cop", "k_cop", "", 2, 0]);
    // Standby nur, wenn die Statistik den ganzen Zeitraum abdeckt
    const sbCov = r ? this._standbyCoverage(r) : { ok: true };
    if (!sbCov.ok) { cur = { ...cur, standby: null }; if (prev) prev = { ...prev, standby: null }; }
    // Aufteilung, Starts und Laufzeit gibt es nur aus den Zaehlern
    const since = this._since ? this._date(this._since, { day: "numeric", month: "short" }) : "";
    const splitKeys = ["az_heat", "az_dhw", "dhw_share"], counterKeys = ["starts", "runtime", "run_per_start", "starts_h"];
    const note = (k) => {
      if (!tot || !this._since) return "";
      if (splitKeys.includes(k) && tot.split_partial) return this._t("only_since", { since });
      if (counterKeys.includes(k) && tot.counters_partial) return this._t("only_since", { since });
      return "";
    };
    // Kacheln ohne jede moegliche Quelle im Zeitraum: statt leerer Kacheln eine
    // Zeile "Erst ab <Datum> verfuegbar: ..." (Schluessel: Datum in ms oder "none")
    const unavailable = new Map();
    const park = (when, label) => {
      const key = isNum(when) ? when : "none";
      if (!unavailable.has(key)) unavailable.set(key, []);
      unavailable.get(key).push(this._t(label));
    };
    let incomplete = false;
    // Arbeitszahl nur aus einem Teil der Zeit mit Strom (Waerme fehlt oder unplausibel)
    const azPart = tot && isNum(cur.az) && isNum(tot.cov_el) && tot.cov_el > 0 && (tot.cov_az || 0) < 0.95 * tot.cov_el
      ? Math.round((100 * (tot.cov_az || 0)) / tot.cov_el) : null;
    const tile = ([k, label, unit, d, dir, abs]) => {
      const v = cur[k], p = prev ? prev[k] : null;
      let nt = note(k) || (k === "az" && (azPart !== null || (tot && tot.bad_days > 0)) ? this._t("az_partial") : "");
      const missing = tot && !isNum(v) && ((counterKeys.includes(k) && tot.counters_none) || (splitKeys.includes(k) && tot.n_data > 0 && !tot.n_th_split));
      // Keine Zaehler-Daten im ganzen Zeitraum: kompakt "erst ab <Beginn der Zaehler>"
      if (missing) { park(this._since ? this._since.getTime() : null, label); return ""; }
      if (k === "standby" && !sbCov.ok) {
        // Statistik beginnt erst nach dem Zeitraum (oder gar nicht): kompakt
        if (!isNum(sbCov.from) || !r || sbCov.from >= Math.min(r.end.getTime(), now)) { park(sbCov.from, label); return ""; }
        nt = this._t("from_date", { since: this._date(new Date(sbCov.from), dateLong) });
      }
      const est = tot && tot.estimated && ["el", "th", "az", "kwh_hdd"].includes(k) && isNum(v)
        && ((k === "el" && tot.srcEl.has("mean")) || (k === "th" && tot.srcTh.has("mean")) || (k === "az") || (k === "kwh_hdd" && tot.srcEl.has("mean")));
      let delta = "";
      const pc = isNum(v) && isNum(p) ? this._prevCoverage(k, tot, prevTot) : null;
      // Vorzeitraum mit zu wenig Daten: kein Delta (Fussnote, Hinweis am Wert)
      if (pc !== null) incomplete = true;
      else if (isNum(v) && isNum(p)) {
        let txt = null, val = 0;
        // abs: Differenz in K bzw. Prozentpunkten ("pp"), sonst relativ in %
        if (abs) { val = v - p; txt = `${signed(val, this._num(Math.abs(val), 1))} ${abs === "pp" ? this._t("pp") : "K"}`; }
        else if (Math.abs(p) > 1e-9) { val = ((v - p) / Math.abs(p)) * 100; txt = `${signed(val, this._num(Math.abs(val), 0))} %`; }
        if (txt !== null) {
          const good = dir === 0 || Math.abs(val) < 0.5 ? "" : (val > 0) === (dir > 0) ? "good" : "bad";
          delta = `<span class="delta ${good}" title="${esc(this._t("vs_prev"))}: ${esc(this._num(p, d))}${unit ? ` ${esc(unit)}` : ""}">${txt}</span>`;
        }
      }
      let title = k === "hdd" || k === "kwh_hdd" ? this._t("hdd_hint", { base: this._num(this._base, 0) }) : "";
      if (k === "az" && nt) title = this._t("az_partial_title", { p: azPart !== null ? azPart : 100 });
      if (k === "carnot") {
        title = this._t("carnot_title");
        if (isNum(v) && tot && tot.cn_daily > 0) { nt = nt || this._t("carnot_daily"); title += ` ${this._t("carnot_daily_title")}`; }
      }
      if (k === "standby") {
        title = this._t("standby_title");
        if (isNum(v) && (isNum(cur.standby_w) || isNum(cur.standby_share))) {
          nt = this._t("standby_sub", { w: this._num(cur.standby_w, 0), p: this._num(cur.standby_share, 1) });
        }
      }
      // Takten: Warnfarbe mit denselben Schwellen wie binary_sensor takten
      let warn = false;
      if (k === "starts_h" || k === "run_per_start") {
        title = [title, this._t("takt_title", { n: TAKT_MAX_STARTS_PER_H, m: TAKT_MIN_RUN_MIN })].filter(Boolean).join(" · ");
        warn = isNum(v) && (k === "starts_h" ? v > TAKT_MAX_STARTS_PER_H : v < TAKT_MIN_RUN_MIN);
      }
      if (pc !== null) title = [title, this._t("prev_incomplete_tile", { p: pc })].filter(Boolean).join(" · ");
      return `<div class="kpi ${isNum(v) ? "" : "empty"}${warn ? " warnv" : ""}" data-k="${k}"${title ? ` title="${esc(title)}"` : ""}><div class="kl">${esc(this._t(label))}</div>
        <div class="kv">${est ? "≈ " : ""}${this._num(v, d)}${unit && isNum(v) ? `<span class="ku">${esc(unit)}</span>` : ""}</div>${delta}${nt ? `<div class="kn">${esc(nt)}</div>` : ""}</div>`;
    };
    const html = groups.map(([g, defs]) => {
      const tiles = defs.map(tile).join("");
      return tiles ? `<div class="kg">${esc(this._t(g))}</div>${tiles}` : "";
    }).join("");
    const lines = [...unavailable.entries()]
      .sort(([a], [b]) => (a === "none" ? 1 : b === "none" ? -1 : a - b))
      .map(([when, list]) => `<div class="kna">${esc(when === "none"
        ? this._t("avail_none", { list: list.join(", ") })
        : this._t("avail_from", { since: this._date(new Date(when), dateLong), list: list.join(", ") }))}</div>`).join("");
    const inc = incomplete ? ` · ${esc(this._t("prev_incomplete", { p: Math.round(100 * PREV_COVERAGE_MIN) }))}` : "";
    return `<div class="kpis">${html}${lines}</div><div class="foot">${esc(prev ? this._t("vs_prev") : this._t("vs_prev_none"))}${inc} · ${esc(this._t("hdd_hint", { base: this._num(this._base, 0) }))}</div>`;
  }

  // ── Takten / Verdichterzyklen: Darstellung (v1.4.0) ──────────────────────
  _durTxt(ms) {
    if (!isNum(ms)) return "–";
    const m = Math.round(ms / 60000);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
  }
  _hm(t) { return this._date(new Date(t), { hour: "2-digit", minute: "2-digit" }); }
  _modeLabel(m) { return this._t(`tk_m_${m}`); }

  /** Beginn des Verlaufs als {n Tage, since Datum}. */
  _histInfo() {
    const H = this._hist;
    if (!isNum(H.horizon)) return null;
    return {
      n: Math.max(1, Math.round((Date.now() - H.horizon) / DAY_MS)),
      since: this._date(new Date(H.horizon), { day: "numeric", month: "short", year: "numeric" }),
    };
  }
  _counterSince() {
    const f = this._first?.starts;
    return isNum(f) ? this._date(new Date(f), { day: "numeric", month: "short", year: "numeric" }) : null;
  }

  _renderCycles() {
    if (!this._hass || !this._data || !this._cycEnabled()) return "";
    const open = this._tkOpen;
    const head = `<button class="stitle row tk-head" data-action="tk-toggle" aria-expanded="${open}"><span>${esc(this._t("tk_title"))}</span><span class="chev${open ? " on" : ""}" aria-hidden="true">›</span></button>`;
    this._tkTips = {};
    this._tkDrill = {};
    if (!open) return `<div class="section tk">${head}</div>`;
    const r = this._data.range;
    let body;
    if (!CYCLE_VIEWS.includes(r.view)) body = this._renderCyclesLong(r);
    else if (this._cyc?.error) body = `<div class="msg err">${esc(this._t("tk_err"))}: ${esc(this._cyc.error)}</div>`;
    else if (this._hist.horizon === undefined || this._cyc?.loading) body = `<div class="msg dim">${esc(this._t("tk_loading"))}</div>`;
    else body = this._renderCyclesRange(r);
    return `<div class="section tk">${head}${body}</div>`;
  }

  _renderCyclesRange(r) {
    const v = this._cycleView();
    if (!v) return "";
    const S = v.sum, info = this._histInfo(), csince = this._counterSince();
    const notes = [];
    const hasHist = v.days.some((d) => d.hist && d.hist.covMs > 0);
    if (this._hist.horizon === null && !S.nCounter) {
      const freq = this._entities.frequency;
      return `<div class="msg info">${esc(this._hass.states[freq] ? this._t("tk_no_history") : this._t("tk_missing", { id: freq }))}</div>`;
    }
    if (!S.has && !hasHist) {
      return `<div class="msg info">${esc(this._t("tk_no_data", { n: info ? info.n : "?", since: info ? info.since : "–", csince: csince || "–" }))}</div>`;
    }
    if (hasHist && info) notes.push(this._t("tk_src_hist", info));
    if (S.nCounter) notes.push(this._t("tk_src_counter", { n: S.nCounter }));
    if (info && this._hist.horizon > r.start.getTime()) notes.push(this._t("tk_partial", { since: info.since, csince: csince || "–" }));
    if (S.nCounter && hasHist) notes.push(this._t("tk_mixed"));
    const chart = r.view === "day" ? this._tkGantt(v, r) : this._tkDayBars(v, r);
    const legend = this._tkLegend(r.view, v);
    return `${chart ? `<div class="tk-chart">${chart}<div class="tk-tip" hidden></div></div>` : ""}
      ${legend}
      ${this._tkTiles(S, r.view)}
      ${S.durs.length || S.pauses.length ? `<div class="tk-hists">${this._tkHist(this._t("tk_hist_run"), S.durs, "tk_cycles_n")}${this._tkHist(this._t("tk_hist_pause"), S.pauses, "tk_pauses_n")}</div>` : ""}
      <div class="foot">${notes.map((x) => esc(x)).join(" · ")}</div>`;
  }

  _tkLegend(view, v) {
    const used = new Set();
    if (view === "day") for (const c of v.rec.cycles) for (const sg of c.segs || []) used.add(sg.mode);
    else for (const d of v.days) if (d.split) for (const [m, n] of Object.entries(d.split)) if (n) used.add(m);
    const parts = CYCLE_MODES.filter((m) => used.has(m) || m === "heating" || m === "dhw")
      .map((m) => `<i class="sw tk-${m}"></i>${esc(this._modeLabel(m))}`);
    if (view !== "day") {
      if (v.days.some((d) => d.src && !d.split && d.starts > 0)) parts.push(`<i class="sw tk-counter"></i>${esc(this._t("tk_unsplit"))}`);
      parts.push(`<i class="sw line tk-run"></i>${esc(this._t("tk_line"))}`);
      parts.push(`<i class="sw tk-warnsw"></i>${esc(this._t("tk_warn_day"))}`);
    } else {
      if (v.rec.gaps.length) parts.push(`<i class="sw tk-gapsw"></i>${esc(this._t("tk_gap"))}`);
    }
    return `<div class="legend"><span class="sub">${parts.join(" ")}</span></div>`;
  }

  /** Zeitstrahl der Verdichterlaeufe ueber den Tag. */
  _tkGantt(v, r) {
    const w = Math.max(280, this._chartW || this._width || this.clientWidth || 600);
    const narrow = w < 480;
    const left = 6, right = 6, top = 6, lane = 28, h = top + lane + 20;
    const pw = w - left - right;
    const s0 = r.start.getTime(), e0 = r.end.getTime(), now = Date.now();
    const x = (t) => left + ((Math.min(Math.max(t, s0), e0) - s0) / (e0 - s0)) * pw;
    let s = `<defs><pattern id="tk-hatch" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)"><rect class="tk-hatch-line" x="0" y="0" width="2" height="5"/></pattern></defs>`;
    s += `<rect class="tk-lane" x="${left}" y="${top}" width="${pw}" height="${lane}" rx="3"/>`;
    // ohne Verlauf (vor dem Beginn des Verlaufs, nicht geladen) und Luecken
    let t0 = s0;
    const until = Math.min(e0, now);
    for (const l of [...v.rec.loaded, { a: until, b: until }]) {
      const a = Math.max(l.a, s0);
      if (a > t0 && t0 < until) s += `<rect class="tk-na" x="${x(t0).toFixed(1)}" y="${top}" width="${(x(Math.min(a, until)) - x(t0)).toFixed(1)}" height="${lane}"/>`;
      t0 = Math.max(t0, l.b);
    }
    for (const g of v.rec.gaps) {
      if (g.b <= s0 || g.a >= e0) continue;
      s += `<rect class="tk-gap" x="${x(g.a).toFixed(1)}" y="${top}" width="${Math.max(1, x(g.b) - x(g.a)).toFixed(1)}" height="${lane}"><title>${esc(this._t("tk_gap"))}</title></rect>`;
    }
    // Stundenraster (Uhrzeit, auch an Tagen mit Zeitumstellung)
    const step = narrow ? 6 : 3;
    for (let hh = 0; hh <= 24; hh += step) {
      const d = new Date(r.start); d.setHours(hh, 0, 0, 0);
      const t = hh === 24 ? e0 : d.getTime();
      const xx = x(t).toFixed(1);
      s += `<line class="grid" x1="${xx}" x2="${xx}" y1="${top}" y2="${top + lane + 3}"/>`;
      s += `<text class="ax" x="${xx}" y="${h - 4}" text-anchor="${hh === 0 ? "start" : hh === 24 ? "end" : "middle"}">${String(hh).padStart(2, "0")}</text>`;
    }
    // Laeufe, je Abschnitt nach Betriebsart gefaerbt
    v.rec.cycles.forEach((c, i) => {
      if (c.end <= s0 || c.start >= e0) return;
      const inc = c.complete ? "" : " tk-inc";
      for (const sg of c.segs || []) {
        if (sg.b <= s0 || sg.a >= e0) continue;
        const xa = x(sg.a), xb = x(sg.b);
        s += `<rect class="tk-${sg.mode}${inc}" x="${xa.toFixed(1)}" y="${top + 2}" width="${Math.max(1.2, xb - xa).toFixed(1)}" height="${lane - 4}"/>`;
      }
      const xa = x(c.start), xb = x(c.end), cx = (xa + xb) / 2, hw = Math.max(5, (xb - xa) / 2);
      const id = `c:${i}`;
      this._tkTips[id] = this._tkCycleTip(c);
      s += `<rect class="tk-hit" data-tk="${id}" x="${(cx - hw).toFixed(1)}" y="${top - 2}" width="${(2 * hw).toFixed(1)}" height="${lane + 4}"/>`;
    });
    if (now > s0 && now < e0) s += `<line class="now" x1="${x(now).toFixed(1)}" x2="${x(now).toFixed(1)}" y1="${top}" y2="${top + lane}"/>`;
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" role="img" aria-label="${esc(this._t("tk_title"))}">${s}</svg>`;
  }

  _tkCycleTip(c) {
    const row = (l, val, sw = "") => `<tr><td>${sw ? `<i class="sw ${sw}"></i>` : ""}${esc(l)}</td><td>${esc(val)}</td></tr>`;
    const dOpts = { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };
    const flags = [];
    if (c.openStart) flags.push(this._t("tk_open_start"));
    if (c.cut) flags.push(this._t("tk_cut"));
    if (c.openEnd) flags.push(this._t("tk_open_end"));
    const modes = CYCLE_MODES.filter((m) => (c.modeMs?.[m] || 0) >= 30000)
      .map((m) => row(this._modeLabel(m), this._durTxt(c.modeMs[m]), `tk-${m}`)).join("");
    return `<div class="tt">${esc(this._hm(c.start))} – ${esc(this._hm(c.end))}</div><table>
      ${row(this._t("tk_begin"), (c.openStart ? "≤ " : "") + this._date(new Date(c.start), dOpts))}
      ${row(this._t("tk_dur"), c.complete ? this._durTxt(c.dur) : `≥ ${this._durTxt(c.end - c.start)}`)}
      ${row(this._t("tk_pause_before"), isNum(c.pause) ? this._durTxt(c.pause) : "–")}
      ${row(this._t("tk_mode"), this._modeLabel(c.mode))}
      ${modes}</table>${flags.length ? `<div class="dim warnt">${esc(flags.join(" · "))}</div>` : ""}`;
  }

  /** Woche/Monat: Starts je Tag (gestapelt nach Betriebsart) + Ø Laufzeit. */
  _tkDayBars(v, r) {
    const items = v.days.map((d, i) => {
      const stack = [];
      if (d.src && d.split) for (const m of CYCLE_MODES) { if (d.split[m]) stack.push([d.split[m], `tk-${m}`]); }
      else if (d.src && d.starts > 0) stack.push([d.starts, d.src === "counter" ? "tk-counter" : "tk-other"]);
      const id = `d:${i}`;
      this._tkTips[id] = this._tkDayTip(d, r.buckets[i], r.view);
      this._tkDrill[id] = i;
      return { stack, total: d.src ? d.starts || 0 : 0, line: d.avgRun, warn: d.src && d.warn, partial: d.src === "hist" && d.hist.cov < 0.98, id };
    });
    return this._tkBars(items, r);
  }

  _tkDayTip(d, day, view) {
    const row = (l, val, sw = "") => `<tr><td>${sw ? `<i class="sw ${sw}"></i>` : ""}${esc(l)}</td><td>${esc(val)}</td></tr>`;
    const h = d.hist;
    let rows = "";
    if (d.src) {
      rows += row(this._t("tk_starts"), this._num(d.starts, 0));
      if (d.split) for (const m of CYCLE_MODES) if (d.split[m]) rows += row(`  ${this._modeLabel(m)}`, this._num(d.split[m], 0), `tk-${m}`);
      rows += row(this._t("tk_avg_run"), isNum(d.avgRun) ? this._durTxt(d.avgRun * 60000) : "–");
      if (isNum(d.runH)) rows += row(this._t("k_runtime"), `${this._num(d.runH, 1)} h`);
      if (h && h.pauses.length) rows += row(this._t("tk_avg_pause"), this._durTxt(h.pauses.reduce((a, b) => a + b, 0) / h.pauses.length));
      if (isNum(d.max60)) rows += row(this._t("tk_max60"), this._num(d.max60, 0));
      rows += `<tr class="src"><td>${esc(this._t("src"))}</td><td>${esc(d.src === "counter" ? this._t("src_counter") : this._t("tk_src_short"))}</td></tr>`;
    }
    const notes = [];
    if (!d.src) notes.push(this._t("tk_day_none"));
    if (d.src === "hist" && h.cov < 0.98) notes.push(this._t("tk_day_partial", { p: Math.round(100 * h.cov) }));
    if (h && h.gapMs > 0) notes.push(`${this._t("tk_gap")}: ${this._durTxt(h.gapMs)}`);
    const warn = d.src && d.warn ? `<div class="dim warnt">${esc(this._t("tk_warn_day"))} (${esc(this._t("takt_title", { n: TAKT_MAX_STARTS_PER_H, m: TAKT_MIN_RUN_MIN }))})</div>` : "";
    return `<div class="tt">${esc(this._bucketLabel(view, day))}</div><table>${rows}</table>${warn}${notes.length ? `<div class="dim">${esc(notes.join(" · "))}</div>` : ""}`;
  }

  /** Balken (Starts, linke Achse) + Linie (Ø Laufzeit in min, rechte Achse). */
  _tkBars(items, r) {
    const w = Math.max(280, this._chartW || this._width || this.clientWidth || 600);
    const narrow = w < 480;
    const h = narrow ? 180 : 210;
    const left = 30, right = 36, top = 16, bottom = 22;
    const pw = w - left - right, ph = h - top - bottom;
    const n = items.length, gw = pw / n;
    const maxT = Math.max(0, ...items.map((it) => it.total));
    let stepY = 1;
    for (const m of [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]) { stepY = m; if (m * 4 >= maxT) break; }
    const maxY = stepY * 4;
    const y = (v) => top + ph - (v / maxY) * ph;
    const lines = items.map((it) => it.line).filter(isNum);
    const maxR = niceMax(Math.max(TAKT_MIN_RUN_MIN * 2, ...lines));
    const yR = (v) => top + ph - (Math.min(v, maxR) / maxR) * ph;
    let s = "";
    for (let i = 0; i <= 4; i++) {
      const yy = y(stepY * i);
      s += `<line class="grid" x1="${left}" x2="${left + pw}" y1="${yy}" y2="${yy}"/>`;
      s += `<text class="ax" x="${left - 5}" y="${yy + 3}" text-anchor="end">${this._num(stepY * i, 0)}</text>`;
      s += `<text class="ax tk-runax" x="${left + pw + 5}" y="${yR((maxR / 4) * i) + 3}">${this._num((maxR / 4) * i, 0)}</text>`;
    }
    s += `<text class="ax unit" x="${left - 5}" y="${top - 5}" text-anchor="end">${esc(this._t("tk_axis_starts"))}</text>`;
    s += `<text class="ax tk-runax unit" x="${left + pw + 5}" y="${top - 5}">min</text>`;
    // Schwelle 10 min (rechte Achse)
    s += `<line class="tk-thr" x1="${left}" x2="${left + pw}" y1="${yR(TAKT_MIN_RUN_MIN).toFixed(1)}" y2="${yR(TAKT_MIN_RUN_MIN).toFixed(1)}"/>`;
    const bw = Math.max(2, Math.min(26, gw * 0.62));
    items.forEach((it, i) => {
      const cx = left + gw * (i + 0.5);
      let acc = 0;
      for (const [val, cls] of it.stack) {
        if (!(val > 0)) continue;
        const y1 = y(acc + val), y0 = y(acc);
        s += `<rect class="${cls}${it.partial ? " tk-part" : ""}" x="${(cx - bw / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0.5, y0 - y1).toFixed(1)}" rx="1"/>`;
        acc += val;
      }
      if (it.warn) {
        const yt = y(acc) - 4;
        s += `<path class="tk-warnmark" d="M${(cx - 4).toFixed(1)} ${(yt - 6).toFixed(1)}h8l-4 6z"/>`;
        if (acc > 0) s += `<rect class="tk-warnbox" x="${(cx - bw / 2 - 1).toFixed(1)}" y="${(y(acc) - 1).toFixed(1)}" width="${(bw + 2).toFixed(1)}" height="${(y(0) - y(acc) + 1).toFixed(1)}" rx="1.5"/>`;
      }
    });
    // Linie Ø Laufzeit
    let d = "", dots = "", pen = false;
    items.forEach((it, i) => {
      const cx = left + gw * (i + 0.5);
      if (!isNum(it.line)) { pen = false; return; }
      const yy = yR(it.line).toFixed(1);
      d += `${pen ? "L" : "M"}${cx.toFixed(1)} ${yy}`;
      pen = true;
      dots += `<circle class="tk-run${it.line < TAKT_MIN_RUN_MIN ? " low" : ""}" cx="${cx.toFixed(1)}" cy="${yy}" r="${n <= 14 ? 3 : 2.2}"/>`;
    });
    if (d) s += `<path class="tk-run ln" d="${d}"/>${dots}`;
    const stepX = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / (r.view === "week" ? (narrow ? 22 : 44) : 30)))));
    r.buckets.forEach((b, i) => {
      if (i % stepX !== 0) return;
      s += `<text class="ax" x="${(left + gw * (i + 0.5)).toFixed(1)}" y="${h - 6}" text-anchor="middle">${esc(this._xLabel(r.view, b, narrow))}</text>`;
    });
    const now = Date.now();
    if (now > r.start.getTime() && now < r.end.getTime()) {
      const j = r.buckets.findIndex((b, i) => now >= b.getTime() && now < r.ends[i].getTime());
      if (j >= 0) {
        const xn = (left + gw * (j + (now - r.buckets[j].getTime()) / (r.ends[j].getTime() - r.buckets[j].getTime()))).toFixed(1);
        s += `<line class="now" x1="${xn}" x2="${xn}" y1="${top}" y2="${top + ph}"/>`;
      }
    }
    items.forEach((it, i) => {
      if (it.id) s += `<rect class="tk-hit" data-tk="${it.id}" x="${(left + gw * i).toFixed(1)}" y="${top - 10}" width="${gw.toFixed(1)}" height="${ph + 10}"/>`;
    });
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" role="img" aria-label="${esc(this._t("tk_title"))}">${s}</svg>`;
  }

  _tkTiles(S, view) {
    const fmtMin = (m) => (isNum(m) ? (m >= 100 ? [this._num(m / 60, 1), "h"] : [this._num(m, 0), "min"]) : ["–", ""]);
    const defs = [
      ["tk_starts", [this._num(S.has ? S.starts : null, 0), ""]],
      ...(view !== "day" ? [["tk_starts_day", [this._num(S.startsDay, 1), ""]]] : []),
      ["tk_avg_run", fmtMin(S.avgRun), isNum(S.avgRun) && S.avgRun < TAKT_MIN_RUN_MIN],
      ["tk_min_run", fmtMin(S.minRun), isNum(S.minRun) && S.minRun < TAKT_MIN_RUN_MIN],
      ["tk_max_run", fmtMin(S.maxRun)],
      ["tk_avg_pause", fmtMin(S.avgPause)],
      ["tk_max_pause", fmtMin(S.maxPause)],
      ["k_starts_h", [this._num(S.startsH, 1), "/h"], isNum(S.startsH) && S.startsH > TAKT_MAX_STARTS_PER_H],
      ["tk_short", [this._num(S.short, 0), "%"], isNum(S.short) && S.short > 0],
      ["tk_max60", [this._num(S.max60, 0), ""], isNum(S.max60) && S.max60 > TAKT_MAX_STARTS_PER_H],
    ];
    const title = this._t("takt_title", { n: TAKT_MAX_STARTS_PER_H, m: TAKT_MIN_RUN_MIN });
    return `<div class="kpis tk-kpis">${defs.map(([label, [val, unit], warn]) => `<div class="kpi${val === "–" ? " empty" : ""}${warn ? " warnv" : ""}" title="${esc(title)}"><div class="kl">${esc(this._t(label))}</div><div class="kv">${val}${unit && val !== "–" ? `<span class="ku">${esc(unit)}</span>` : ""}</div></div>`).join("")}</div>`;
  }

  /** Histogramm (Klassen CYCLE_BINS) als HTML-Balken. */
  _tkHist(title, list, countKey) {
    const counts = new Array(CYCLE_BINS.length + 1).fill(0);
    for (const ms of list) counts[binOf(ms)]++;
    const max = Math.max(1, ...counts);
    const labels = [`< ${CYCLE_BINS[0]}`, ...CYCLE_BINS.slice(1).map((b, i) => `${CYCLE_BINS[i]}–${b}`), `> ${CYCLE_BINS[CYCLE_BINS.length - 1]}`];
    const rows = counts.map((c, i) => `<div class="hrow"><span class="hl">${esc(labels[i])} min</span><span class="hb"><i class="${i === 0 ? "short" : ""}" style="width:${((100 * c) / max).toFixed(1)}%"></i></span><span class="hn">${c}</span></div>`).join("");
    return `<div class="tk-hist"><div class="tk-htitle">${esc(title)} <span class="dim">· ${esc(this._t(countKey, { n: list.length }))}</span></div>${rows}</div>`;
  }

  /** Jahr/Alle Jahre: Starts und Ø Laufzeit je Monat/Jahr nur aus den Zaehlern. */
  _renderCyclesLong(r) {
    const bars = this._bars || [];
    const info = this._histInfo(), csince = this._counterSince();
    const hint = this._t("tk_long_hint", { since: csince || "–", n: info ? info.n : "?" });
    if (!bars.some((b) => isNum(b.starts))) return `<div class="msg info">${esc(this._t("tk_long_none", { n: info ? info.n : "?" }))}</div>`;
    const items = bars.map((b, i) => {
      const ok = isNum(b.starts);
      const line = ok && isNum(b.runtime) && b.starts > 0 ? (60 * b.runtime) / b.starts : null;
      const sh = ok && isNum(b.runtime) && b.runtime >= 0.5 ? b.starts / b.runtime : null;
      const id = `d:${i}`;
      const row = (l, val) => `<tr><td>${esc(l)}</td><td>${esc(val)}</td></tr>`;
      this._tkTips[id] = `<div class="tt">${esc(this._bucketLabel(r.view, r.buckets[i]))}</div><table>${ok
        ? row(this._t("tk_starts"), this._num(b.starts, 0)) + row(this._t("tk_avg_run"), isNum(line) ? this._durTxt(line * 60000) : "–")
          + (isNum(b.runtime) ? row(this._t("k_runtime"), `${this._num(b.runtime, 1)} h`) : "")
          + `<tr class="src"><td>${esc(this._t("src"))}</td><td>${esc(this._t("src_counter"))}</td></tr>`
        : row(this._t("tk_starts"), "–")}</table>`;
      this._tkDrill[id] = i;
      return { stack: ok && b.starts > 0 ? [[b.starts, "tk-counter"]] : [], total: ok ? b.starts : 0, line, id,
        warn: (isNum(line) && line < TAKT_MIN_RUN_MIN) || (isNum(sh) && sh > TAKT_MAX_STARTS_PER_H) };
    });
    const tot = bars.reduce((a, b) => (isNum(b.starts) ? { s: a.s + b.starts, h: a.h + (b.runtime || 0) } : a), { s: 0, h: 0 });
    const S = { has: true, starts: tot.s, avgRun: tot.s > 0 ? (60 * tot.h) / tot.s : null, startsH: tot.h >= 0.5 ? tot.s / tot.h : null };
    const fmt = (m) => (isNum(m) ? (m >= 100 ? [this._num(m / 60, 1), "h"] : [this._num(m, 0), "min"]) : ["–", ""]);
    const tiles = [["tk_starts", [this._num(S.starts, 0), ""]], ["tk_avg_run", fmt(S.avgRun), isNum(S.avgRun) && S.avgRun < TAKT_MIN_RUN_MIN],
      ["k_runtime", [this._num(tot.h, 1), "h"]], ["k_starts_h", [this._num(S.startsH, 1), "/h"], isNum(S.startsH) && S.startsH > TAKT_MAX_STARTS_PER_H]];
    return `<div class="tk-chart">${this._tkBars(items, r)}<div class="tk-tip" hidden></div></div>
      <div class="legend"><span class="sub"><i class="sw tk-counter"></i>${esc(this._t("tk_starts"))} <i class="sw line tk-run"></i>${esc(this._t("tk_line"))} <i class="sw tk-warnsw"></i>${esc(this._t("tk_warn_day"))}</span></div>
      <div class="kpis tk-kpis">${tiles.map(([l, [val, u], warn]) => `<div class="kpi${val === "–" ? " empty" : ""}${warn ? " warnv" : ""}"><div class="kl">${esc(this._t(l))}</div><div class="kv">${val}${u && val !== "–" ? `<span class="ku">${esc(u)}</span>` : ""}</div></div>`).join("")}</div>
      <div class="foot">${esc(hint)}</div>`;
  }

  _updateTkTip() {
    const tip = this.shadowRoot.querySelector(".tk-tip");
    if (!tip) return;
    const t = this._tkTip, html = t && this._tkTips?.[t.id];
    const el = html ? this.shadowRoot.querySelector(`[data-tk="${t.id}"]`) : null;
    if (!html || !el) { tip.hidden = true; return; }
    const drill = t.sticky && this._tkDrill?.[t.id] !== undefined && { all: 1, year: 1, month: 1, week: 1 }[this._data?.range?.view]
      ? `<button class="link" data-action="drill" data-index="${this._tkDrill[t.id]}">${esc(this._t("show"))} ›</button>` : "";
    tip.innerHTML = html + drill;
    tip.hidden = false;
    const box = tip.parentElement;
    const br = box.getBoundingClientRect(), er = el.getBoundingClientRect();
    const cw = box.clientWidth || br.width || 300;
    const px = er.left + er.width / 2 - br.left;
    const tw = tip.offsetWidth || 200;
    let lx = px + 12;
    if (lx + tw > cw) lx = Math.max(0, px - tw - 12);
    tip.style.left = `${lx}px`;
    tip.style.top = "4px";
    tip.classList.toggle("sticky", !!t.sticky);
  }

  _renderChanges() {
    if (!this._hass) return "";
    let body;
    if (this._changesError) body = `<div class="msg dim">${esc(this._t("err_changes"))}</div>`;
    else if (!this._changes) body = "";
    else if (!this._changes.length) body = `<div class="msg dim">${esc(this._t("changes_none"))}</div>`;
    else {
      const r = this._data?.range;
      const list = this._changes.map((c, i) => [c, i]).reverse();
      const shown = this._showAllChanges ? list : list.slice(0, 6);
      body = `<ul class="changes">${shown.map(([c, i]) => {
        const inR = r && c._t >= r.start && c._t < r.end;
        const items = c.items.slice(0, 3).map((it) => esc(this._itemText(it))).join(" · ");
        const more = c.items.length > 3 ? ` <span class="dim">${esc(this._t("more_items", { n: c.items.length - 3 }))}</span>` : "";
        return `<li><button class="change ${this._compare?.index === i ? "on" : ""}" data-action="change" data-index="${i}">
          <span class="cd">${inR ? `<i class="dot" title="${esc(this._t("in_range"))}"></i>` : ""}${esc(this._date(c._t, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))}<span class="dim"> · ${esc(this._reason(c.reason))}</span></span>
          <span class="ci">${items}${more}</span></button></li>`;
      }).join("")}</ul>${list.length > 6 ? `<button class="link" data-action="more-changes">${esc(this._showAllChanges ? this._t("changes_less") : this._t("changes_more", { n: list.length }))}</button>` : ""}`;
    }
    return `<div class="section"><div class="stitle">${esc(this._t("changes"))}</div>${body}</div>`;
  }

  _renderCompare() {
    const c = this._compare;
    if (!c) return "";
    const ch = c.change;
    const dayBtns = [3, 7, 14, 30].map((d) => `<button class="tab small ${d === this._compareDays ? "on" : ""}" data-action="compare-days" data-days="${d}">${d}</button>`).join("");
    const items = ch.items.map((it) => `<li>${esc(this._itemText(it))}</li>`).join("");
    let body = "";
    if (c.loading) body = `<div class="msg">${esc(this._t("loading"))}</div>`;
    else if (c.error) body = `<div class="msg err">${esc(this._t("err_stats"))}: ${esc(c.error)}</div>`;
    else {
      const metric = (side) => {
        const t = side.tot, d = side.days || 0;
        const k = this._kpis(t);
        return {
          az: k.az,
          carnot: k.carnot,
          el_day: t.n_el && isNum(t.el) ? t.el / t.n_el : null,
          th_day: t.n_th && isNum(t.th) ? t.th / t.n_th : null,
          kwh_hdd: k.kwh_hdd,
          // Zaehler, sonst aus dem Verlauf rekonstruiert (side.takt, je Tag eine Quelle)
          starts_day: side.takt ? side.takt.startsDay : (t.n_starts && isNum(t.starts) ? t.starts / t.n_starts : null),
          run_per_start: side.takt ? side.takt.avgRun : k.run_per_start,
          starts_h: side.takt ? side.takt.startsH : k.starts_h,
          pause: side.takt ? side.takt.avgPause : null,
          short: side.takt ? side.takt.short : null,
          outdoor: t.outdoor,
          flow: t.flow,
          days: d,
        };
      };
      const b = metric(c.before), a = metric(c.after);
      const defs = [
        ["az", "c_az", "", 2, 1], ["carnot", "c_carnot", "%", 0, 1, "pp"], ["el_day", "c_el_day", "kWh", 1, -1], ["th_day", "c_th_day", "kWh", 1, 0],
        ["kwh_hdd", "c_kwh_hdd", "kWh/Kd", 2, -1], ["starts_day", "c_starts_day", "", 1, -1],
        ["run_per_start", "c_run_per_start", "min", 0, 1], ["starts_h", "k_starts_h", "/h", 1, -1],
        ["pause", "c_pause", "min", 0, 1], ["short", "c_short", "%", 0, -1, "pp"],
        ["outdoor", "c_outdoor", "°C", 1, 0, true],
        ["flow", "c_flow", "°C", 1, 0, true], ["days", "c_days", "", 0, 0, null],
      ];
      const rows = defs.map(([k, label, unit, d, dir, abs]) => {
        const vb = b[k], va = a[k];
        let delta = "–", cls = "";
        if (abs !== null && isNum(vb) && isNum(va)) {
          if (abs) {
            const dv = va - vb;
            delta = `${signed(dv, this._num(Math.abs(dv), 1))} ${abs === "pp" ? this._t("pp") : "K"}`;
            if (abs === "pp" && dir && Math.abs(dv) >= 0.5) cls = (dv > 0) === (dir > 0) ? "good" : "bad";
          }
          else if (Math.abs(vb) > 1e-9) {
            const dv = ((va - vb) / Math.abs(vb)) * 100;
            delta = `${signed(dv, this._num(Math.abs(dv), 0))} %`;
            if (dir && Math.abs(dv) >= 0.5) cls = (dv > 0) === (dir > 0) ? "good" : "bad";
          }
        } else if (abs === null) delta = "";
        const u = unit ? ` <span class="ku">${esc(unit)}</span>` : "";
        const tt = k === "carnot" ? ` title="${esc(this._t("carnot_title"))}"` : "";
        return `<tr${tt}><td>${esc(this._t(label))}</td><td>${this._num(vb, d)}${isNum(vb) ? u : ""}</td><td>${this._num(va, d)}${isNum(va) ? u : ""}</td><td class="delta ${cls}">${delta}</td></tr>`;
      }).join("");
      const hints = [];
      if (!c.before.days && !c.after.days) hints.push(this._t("hint_nodata"));
      if (c.incomplete) hints.push(this._t("hint_incomplete", { n: c.fullAfterDays, m: c.days }));
      if (isNum(b.outdoor) && isNum(a.outdoor) && Math.abs(a.outdoor - b.outdoor) >= TEMP_HINT_K) {
        hints.push(this._t("hint_temp", { d: this._num(Math.abs(a.outdoor - b.outdoor), 1) }));
      }
      if (c.others) hints.push(this._t("hint_overlap", { n: c.others }));
      // Takt-Werte: Verlauf/Zaehler reichen nicht zurueck
      if (this._cycEnabled() && [b, a].some((m) => !isNum(m.starts_day) || !isNum(m.pause))) {
        const info = this._histInfo();
        hints.push(this._t("hint_tk_nohist", { n: info ? info.n : "?", since: info ? info.since : "–", csince: this._counterSince() || "–" }));
      }
      const tempHint = isNum(b.outdoor) && isNum(a.outdoor) && Math.abs(a.outdoor - b.outdoor) >= TEMP_HINT_K;
      if (c.before.tot.bad_days > 0 || c.after.tot.bad_days > 0) hints.push(this._t("hint_implausible"));
      if (c.before.tot.historic || c.after.tot.historic) {
        const srcs = [this._srcList(c.before.tot), this._srcList(c.after.tot)].filter(Boolean);
        hints.push(this._t("hint_estimated", { sources: [...new Set(srcs)].join("; ") }));
      }
      // Erklaerung des Carnot-Guetegrads (neutral, vor dem letzten Hinweis)
      const info = [];
      if (!tempHint && (isNum(b.carnot) || isNum(a.carnot))) info.push(this._t("hint_carnot"));
      if ([c.before.takt, c.after.takt].some((x) => x && x.nHist)) info.push(this._t("hint_tk_src"));
      info.push(this._t("hint_change_day"));
      const nWarn = hints.length;
      hints.push(...info);
      body = `<table class="cmp"><thead><tr><th></th><th>${esc(this._t("before"))}</th><th>${esc(this._t("after"))}</th><th>${esc(this._t("delta"))}</th></tr></thead><tbody>${rows}</tbody></table>
        <ul class="hints">${hints.map((h, i) => `<li class="${i >= nWarn ? "dim" : "warn"}">${esc(h)}</li>`).join("")}</ul>`;
    }
    return `<div class="section compare">
      <div class="stitle row"><span>${esc(this._t("compare"))} · ${esc(this._date(ch._t, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))}</span>
        <button class="icon" data-action="compare-close" title="${esc(this._t("close"))}" aria-label="${esc(this._t("close"))}">×</button></div>
      <div class="dim">${esc(this._reason(ch.reason))}</div>
      <ul class="citems">${items}</ul>
      <div class="days">${dayBtns}<span class="dim">${esc(this._t("compare_days"))}</span></div>
      ${body}</div>`;
  }
}

const STYLE = `
:host {
  --esa-elh: var(--blue-color, #2196f3);
  --esa-eld: var(--light-blue-color, #03a9f4);
  --esa-elr: var(--blue-grey-color, #607d8b);
  --esa-thh: var(--deep-orange-color, #ff5722);
  --esa-thd: var(--amber-color, #ffc107);
  --esa-thr: var(--brown-color, #795548);
  --esa-elu: #90a4ae;              /* Strom, nicht aufgeteilt (Historie) */
  --esa-thu: #bcaaa4;              /* Waerme, nicht aufgeteilt (Historie) */
  --esa-az: var(--success-color, #43a047);
  --esa-temp: var(--purple-color, #9c27b0);
  --esa-good: var(--success-color, #43a047);
  --esa-bad: var(--error-color, #db4437);
  --esa-warn: var(--warning-color, #ffa600);
  --esa-tk-heating: var(--deep-orange-color, #ff5722);
  --esa-tk-dhw: var(--amber-color, #ffc107);
  --esa-tk-defrost: var(--cyan-color, #00bcd4);
  --esa-tk-cooling: var(--blue-color, #2196f3);
  --esa-tk-other: #90a4ae;
  --esa-tk-counter: var(--blue-grey-color, #607d8b);
  --esa-tk-run: var(--indigo-color, #3f51b5);
  display: block;
}
ha-card { padding: 12px 12px 8px; overflow: hidden; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.title { font-size: var(--ha-card-header-font-size, 20px); font-weight: 500; color: var(--ha-card-header-color, var(--primary-text-color)); padding: 4px 4px 8px; }
.spin { width: 16px; height: 16px; border: 2px solid var(--divider-color); border-top-color: var(--primary-color); border-radius: 50%; animation: r 0.8s linear infinite; }
@keyframes r { to { transform: rotate(360deg); } }
button { font: inherit; color: inherit; background: none; border: none; cursor: pointer; padding: 0; }
button:disabled { opacity: 0.35; cursor: default; }
button:focus-visible, .marker:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; background: var(--secondary-background-color); border-radius: 10px; padding: 3px; }
.tab { flex: 1 1 auto; padding: 6px 8px; border-radius: 8px; font-size: 13px; color: var(--secondary-text-color); white-space: nowrap; }
.tab.on { background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color); font-weight: 500; box-shadow: 0 1px 2px rgba(0,0,0,0.15); }
.tab.small { flex: 0 0 auto; padding: 3px 10px; }
.nav { display: flex; align-items: center; justify-content: center; gap: 8px; margin: 8px 0 4px; min-height: 32px; }
.rlabel { font-weight: 500; text-align: center; min-width: 0; }
.icon { width: 32px; height: 32px; border-radius: 50%; font-size: 22px; line-height: 30px; color: var(--primary-text-color); }
.icon:hover:not(:disabled) { background: var(--secondary-background-color); }
.link { color: var(--primary-color); font-size: 13px; padding: 4px 6px; }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; font-size: 12px; margin: 4px 0; }
.chip { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 12px; border: 1px solid var(--divider-color); }
.chip.off { opacity: 0.45; text-decoration: line-through; }
.sub { color: var(--secondary-text-color); display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; flex: none; }
.sw.line { height: 3px; border-radius: 2px; }
i.c-elh { background: var(--esa-elh); } i.c-eld { background: var(--esa-eld); } i.c-elr { background: var(--esa-elr); }
i.c-thh { background: var(--esa-thh); } i.c-thd { background: var(--esa-thd); } i.c-thr { background: var(--esa-thr); }
i.c-az { background: var(--esa-az); } i.c-temp { background: var(--esa-temp); }
i.c-elu { background: var(--esa-elu); } i.c-thu { background: var(--esa-thu); }
i.hatch { background: repeating-linear-gradient(45deg, var(--esa-elu) 0 2px, transparent 2px 4px); opacity: 0.8; }
.chart { position: relative; margin: 2px -4px 0; touch-action: pan-y; }
svg { display: block; overflow: visible; }
rect.c-elh { fill: var(--esa-elh); } rect.c-eld { fill: var(--esa-eld); } rect.c-elr { fill: var(--esa-elr); }
rect.c-thh { fill: var(--esa-thh); } rect.c-thd { fill: var(--esa-thd); } rect.c-thr { fill: var(--esa-thr); }
rect.c-elu { fill: var(--esa-elu); } rect.c-thu { fill: var(--esa-thu); }
rect.est { fill-opacity: 0.55; }
rect.hatch { fill: url(#esa-hatch); pointer-events: none; }
.hatch-line { fill: var(--card-background-color, var(--ha-card-background, #fff)); fill-opacity: 0.55; }
.ln { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
path.c-az { stroke: var(--esa-az); } circle.c-az { fill: var(--esa-az); }
circle.c-az.bad { fill: var(--card-background-color, var(--ha-card-background, #fff)); stroke: var(--esa-az); stroke-width: 1.5; stroke-dasharray: 2 1.5; }
path.c-temp { stroke: var(--esa-temp); stroke-dasharray: 4 3; } circle.c-temp { fill: var(--esa-temp); }
.grid { stroke: var(--divider-color, rgba(127,127,127,0.25)); stroke-width: 1; }
.ax { fill: var(--secondary-text-color); font-size: 10px; }
.ax.az { fill: var(--esa-az); } .ax.temp { fill: var(--esa-temp); } .ax.unit { font-weight: 500; }
.now { stroke: var(--primary-color); stroke-dasharray: 2 3; stroke-width: 1; }
.plot-hit { fill: transparent; }
.marker { cursor: pointer; }
.marker line { stroke: var(--esa-warn); stroke-width: 1.5; stroke-dasharray: 3 2; }
.marker path { fill: var(--esa-warn); }
.marker .mhit { fill: transparent; }
.marker:hover line { stroke-width: 2.5; }
.tip { position: absolute; z-index: 2; min-width: 160px; max-width: 260px; padding: 8px 10px; border-radius: 8px; font-size: 12px; pointer-events: none;
  background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color);
  border: 1px solid var(--divider-color); box-shadow: 0 2px 8px rgba(0,0,0,0.2); }
.tip.sticky { pointer-events: auto; }
.tip[hidden] { display: none; }
.tip .tt { font-weight: 500; margin-bottom: 4px; }
.tip table { border-collapse: collapse; width: 100%; }
.tip td { padding: 1px 0; } .tip td:last-child { text-align: right; padding-left: 10px; white-space: nowrap; }
.tip td .sw { margin-right: 4px; vertical-align: -1px; }
.tip ul { margin: 4px 0 0; padding-left: 16px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 6px; margin-top: 10px; }
.kpi { background: var(--secondary-background-color); border-radius: 10px; padding: 8px 10px; min-width: 0; }
.kpi.empty { opacity: 0.55; }
.kpi.warnv .kv { color: var(--esa-warn); }
.kg { grid-column: 1 / -1; font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); margin: 4px 2px -2px; }
.kg:first-child { margin-top: 0; }
.kna { grid-column: 1 / -1; font-size: 12px; color: var(--secondary-text-color); padding: 2px 2px 0; }
.kl { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kv { font-size: 18px; font-weight: 500; margin-top: 2px; white-space: nowrap; }
.ku { font-size: 11px; font-weight: 400; color: var(--secondary-text-color); margin-left: 3px; }
.delta { font-size: 11px; color: var(--secondary-text-color); }
.delta.good { color: var(--esa-good); } .delta.bad { color: var(--esa-bad); }
.kn { font-size: 10px; color: var(--secondary-text-color); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tip tr.src td { color: var(--secondary-text-color); font-size: 11px; }
.foot { font-size: 11px; color: var(--secondary-text-color); margin: 6px 2px 0; }
.msg { padding: 12px 8px; color: var(--primary-text-color); font-size: 14px; }
.msg.err { color: var(--error-color, #db4437); }
.msg.warn { border-left: 3px solid var(--esa-warn); background: var(--secondary-background-color); border-radius: 8px; margin: 6px 0 0; padding: 6px 10px; font-size: 12px; }
.tip .warnt { margin-top: 4px; color: var(--esa-warn); font-size: 11px; }
.msg.info { background: var(--secondary-background-color); border-radius: 8px; margin: 6px 0; padding: 8px 10px; font-size: 13px; }
.dim, .msg.dim { color: var(--secondary-text-color); font-size: 12px; }
.section { margin-top: 14px; border-top: 1px solid var(--divider-color); padding-top: 10px; }
.stitle { font-weight: 500; margin-bottom: 6px; }
.stitle.row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.changes { list-style: none; margin: 0; padding: 0; }
.change { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; width: 100%; padding: 6px 8px; border-radius: 8px; }
.change:hover, .change.on { background: var(--secondary-background-color); }
.cd { font-size: 13px; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ci { font-size: 12px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--esa-warn); display: inline-block; }
.compare { scroll-margin-top: 80px; }
.citems { margin: 4px 0 8px; padding-left: 18px; font-size: 13px; }
.days { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
.cmp { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp th { font-weight: 500; color: var(--secondary-text-color); font-size: 12px; text-align: right; padding: 4px 6px; }
.cmp td { padding: 5px 6px; border-top: 1px solid var(--divider-color); text-align: right; white-space: nowrap; }
.cmp td:first-child, .cmp th:first-child { text-align: left; white-space: normal; }
.cmp td.delta { font-size: 12px; }
.hints { margin: 8px 0 0; padding-left: 18px; font-size: 12px; }
.hints .warn { color: var(--esa-warn); }
/* Takten / Verdichterzyklen (v1.4.0) */
.tk-head { width: 100%; text-align: left; padding: 2px 0; }
.chev { display: inline-block; font-size: 20px; line-height: 1; color: var(--secondary-text-color); transform: rotate(90deg); transition: transform 0.15s; }
.chev.on { transform: rotate(-90deg); }
.tk-chart { position: relative; margin: 4px -4px 0; touch-action: pan-y; }
.tk-tip { position: absolute; z-index: 2; min-width: 170px; max-width: 260px; padding: 8px 10px; border-radius: 8px; font-size: 12px; pointer-events: none;
  background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color);
  border: 1px solid var(--divider-color); box-shadow: 0 2px 8px rgba(0,0,0,0.2); }
.tk-tip.sticky { pointer-events: auto; }
.tk-tip[hidden] { display: none; }
.tk-tip .tt { font-weight: 500; margin-bottom: 4px; }
.tk-tip table { border-collapse: collapse; width: 100%; }
.tk-tip td { padding: 1px 0; white-space: pre; } .tk-tip td:last-child { text-align: right; padding-left: 10px; white-space: nowrap; }
.tk-tip td .sw { margin-right: 4px; vertical-align: -1px; }
.tk-tip tr.src td { color: var(--secondary-text-color); font-size: 11px; }
.tk-tip .warnt { margin-top: 4px; color: var(--esa-warn); font-size: 11px; }
rect.tk-heating, i.tk-heating { fill: var(--esa-tk-heating); background: var(--esa-tk-heating); }
rect.tk-dhw, i.tk-dhw { fill: var(--esa-tk-dhw); background: var(--esa-tk-dhw); }
rect.tk-defrost, i.tk-defrost { fill: var(--esa-tk-defrost); background: var(--esa-tk-defrost); }
rect.tk-cooling, i.tk-cooling { fill: var(--esa-tk-cooling); background: var(--esa-tk-cooling); }
rect.tk-other, i.tk-other { fill: var(--esa-tk-other); background: var(--esa-tk-other); }
rect.tk-counter, i.tk-counter { fill: var(--esa-tk-counter); background: var(--esa-tk-counter); }
i.tk-run { background: var(--esa-tk-run); }
i.tk-warnsw { background: var(--esa-warn); clip-path: polygon(0 0, 100% 0, 50% 100%); }
i.tk-gapsw { background: repeating-linear-gradient(45deg, var(--esa-tk-other) 0 2px, transparent 2px 4px); }
rect.tk-inc { fill-opacity: 0.5; }
rect.tk-part { fill-opacity: 0.6; }
rect.tk-lane { fill: var(--secondary-background-color); }
rect.tk-na { fill: url(#tk-hatch); opacity: 0.6; }
rect.tk-gap { fill: url(#tk-hatch); }
.tk-hatch-line { fill: var(--esa-tk-other); }
rect.tk-hit { fill: transparent; cursor: pointer; }
rect.tk-warnbox { fill: none; stroke: var(--esa-warn); stroke-width: 1.5; }
path.tk-warnmark { fill: var(--esa-warn); }
path.tk-run { stroke: var(--esa-tk-run); } circle.tk-run { fill: var(--esa-tk-run); } circle.tk-run.low { fill: var(--esa-warn); }
.tk-thr { stroke: var(--esa-warn); stroke-width: 1; stroke-dasharray: 3 3; opacity: 0.7; }
.ax.tk-runax { fill: var(--esa-tk-run); }
.tk-hists { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 4px 16px; margin-top: 10px; }
.tk-htitle { font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); margin: 0 0 4px; }
.tk-htitle .dim { text-transform: none; letter-spacing: 0; font-weight: 400; font-size: 11px; }
.hrow { display: grid; grid-template-columns: 68px 1fr 28px; align-items: center; gap: 6px; font-size: 12px; margin: 2px 0; }
.hl { color: var(--secondary-text-color); white-space: nowrap; }
.hb { height: 10px; background: var(--secondary-background-color); border-radius: 3px; overflow: hidden; }
.hb i { display: block; height: 100%; background: var(--esa-tk-run); border-radius: 3px; }
.hb i.short { background: var(--esa-warn); }
.hn { text-align: right; font-variant-numeric: tabular-nums; }
@media (max-width: 420px) {
  ha-card { padding: 10px 8px 6px; }
  .tab { padding: 6px 4px; font-size: 12px; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kv { font-size: 16px; }
  .cmp { font-size: 12px; } .cmp td, .cmp th { padding: 4px 3px; }
}
`;

if (!customElements.get("es-heatpump-analysis-card")) {
  customElements.define("es-heatpump-analysis-card", EsHeatpumpAnalysisCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "es-heatpump-analysis-card",
    name: "ES Heatpump – Auswertung",
    description: "Energie, Arbeitszahl und Verdichter-Takten über Tage, Wochen, Monate und Jahre, mit Vorher/Nachher-Vergleich bei Einstellungsänderungen.",
    preview: false,
    documentationURL: "https://github.com/WombatFirst220/ha-es-heatpump",
  });
  console.info(`%c ES-HEATPUMP-ANALYSIS-CARD %c ${CARD_VERSION} `, "color:#fff;background:#ff5722;font-weight:600", "color:#ff5722");
}
