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
 *
 * Statistiken werden nur bei Zeitraumwechsel und alle 10 Minuten neu geladen,
 * nicht bei jedem hass-Update.
 */

const CARD_VERSION = "1.0.0";
const REFRESH_MS = 10 * 60 * 1000;
const MIN_EL_KWH = 0.05;          // Arbeitszahl je Balken erst ab dieser Strommenge
const AZ_AXIS_MAX = 8;            // Arbeitszahl-Achse wird hier gekappt
const TEMP_HINT_K = 3;            // Aussentemperatur-Unterschied fuer den Hinweis
const DAY_MS = 86400000;

const DEFAULT_ENTITIES = {
  el: "sensor.es_hp_energie_elektrisch",
  el_heat: "sensor.es_hp_energie_elektrisch_heizen",
  el_dhw: "sensor.es_hp_energie_elektrisch_warmwasser",
  th: "sensor.es_hp_energie_thermisch",
  th_heat: "sensor.es_hp_energie_thermisch_heizen",
  th_dhw: "sensor.es_hp_energie_thermisch_warmwasser",
  starts: "sensor.es_hp_verdichter_starts",
  runtime: "sensor.es_hp_verdichter_laufzeit",
  outdoor: "sensor.es_hp_aussentemp_ta",
  cop: "sensor.es_hp_aktueller_cop",
  flow: "sensor.es_hp_vorlauf_tuo",
};
const SUM_KEYS = ["el", "el_heat", "el_dhw", "th", "th_heat", "th_dhw", "starts", "runtime"];
const MEAN_KEYS = ["outdoor", "cop", "flow"];
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
    no_data_range: "Keine Daten in diesem Zeitraum — die Zähler laufen seit {since}.",
    partial_data: "Die Zähler laufen seit {since}; frühere Zeiträume sind leer.",
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
    hint_temp: "Die Außentemperatur unterscheidet sich um {d} K — der Vergleich ist nur bedingt aussagekräftig. Strom je Heizgradtag gleicht das teilweise aus.",
    hint_overlap: "Im Vergleichszeitraum gab es weitere Änderungen ({n}) — die Wirkung lässt sich nicht eindeutig zuordnen.",
    hint_nodata: "Für diesen Zeitraum liegen keine Tageswerte vor.",
    hint_change_day: "Der Tag der Änderung selbst wird nicht mitgezählt.",
    show: "Anzeigen",
    reason: {
      "manuell": "Manuelle Sicherung", "automatisch": "Automatische Sicherung",
      "vor-schreibzugriff": "Vor Schreibzugriff", "vor-wiederherstellung": "Vor Wiederherstellung",
      "erstaufnahme": "Erstaufnahme",
    },
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
    no_data_range: "No data in this period — the counters have been running since {since}.",
    partial_data: "The counters have been running since {since}; earlier periods are empty.",
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
    hint_temp: "Outdoor temperature differs by {d} K — the comparison is of limited value. kWh per heating degree day partly compensates for this.",
    hint_overlap: "There were further changes in the comparison window ({n}) — the effect cannot be attributed unambiguously.",
    hint_nodata: "No daily values for this period.",
    hint_change_day: "The day of the change itself is not counted.",
    show: "Show",
    reason: {
      "manuell": "Manual backup", "automatisch": "Automatic backup",
      "vor-schreibzugriff": "Before write access", "vor-wiederherstellung": "Before restore",
      "erstaufnahme": "Initial snapshot",
    },
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
function ratio(a, b, min = 0) {
  return isNum(a) && isNum(b) && b > min ? a / b : null;
}
function runtimeFactor(unit) {       // Laufzeit in Stunden
  switch (unit) {
    case "s": return 1 / 3600;
    case "min": return 1 / 60;
    case "d": return 24;
    default: return 1;
  }
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
    this._since = undefined;        // erster Statistik-Zeitpunkt (Date|null)
    this._tip = null;               // {index, sticky}
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
    this._entities = { ...DEFAULT_ENTITIES, ...(c.entities && typeof c.entities === "object" ? c.entities : {}) };
    const base = Number(c.heating_base_temp);
    this._base = Number.isFinite(base) ? base : 15;
    if (c.default_view && VIEWS.includes(c.default_view)) this._view = c.default_view;
    this._data = null;
    this._since = undefined;
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
        const firstYear = this._since ? this._since.getFullYear() : now.getFullYear();
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

  _stats(start, end, ids, period, types = ["change", "mean", "min", "max"]) {
    return this._hass.callWS({
      type: "recorder/statistics_during_period",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      statistic_ids: ids,
      period,
      types,
      units: { energy: "kWh" },
    });
  }

  async _reload(silent = false) {
    if (!this._hass || !this._config) return;
    const token = ++this._token;
    if (!silent) { this._loading = true; this._error = null; this._render(); }
    try {
      if (this._since === undefined) await this._loadSince();
      const r = this._range();
      const ids = this._ids([...SUM_KEYS, ...MEAN_KEYS]);
      const qStart = r.prevStart || r.start;
      const [stats, temps] = await Promise.all([
        this._stats(qStart, r.end, ids, r.period),
        this._entities.outdoor
          ? this._stats(qStart, r.end, [this._entities.outdoor], "day", ["mean"])
          : Promise.resolve({}),
      ]);
      if (token !== this._token) return;
      this._data = { range: r, stats: stats || {}, temps: (temps || {})[this._entities.outdoor] || [] };
      this._error = null;
    } catch (err) {
      if (token !== this._token) return;
      this._error = err?.message || err?.code || String(err);
    }
    this._loading = false;
    this._render();
    this._loadChanges(token);
  }

  async _loadSince() {
    // Ohne Strommessung gibt es keinen elektrischen Zaehler - dann zaehlt der
    // thermische. Massgeblich ist der frueheste Beginn beider.
    const ids = this._ids(["el", "th"]);
    try {
      if (!ids.length) { this._since = null; return; }
      const res = await this._stats(new Date(2010, 0, 1), new Date(Date.now() + DAY_MS), ids, "month", ["change"]);
      const firsts = ids.map((id) => ((res && res[id]) || [])[0]).filter(Boolean).map((row) => Number(row.start));
      this._since = firsts.length ? new Date(Math.min(...firsts)) : null;
    } catch (e) {
      this._since = null;
    }
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

  /** Summen/Mittel je Eimer aus Statistikzeilen; rows: {id: [{start, change, mean, min, max}]} */
  _aggregate(stats, starts, ends) {
    const n = starts.length;
    const out = starts.map(() => ({}));
    const s0 = starts.map((d) => d.getTime());
    const e0 = ends.map((d) => d.getTime());
    const rf = this._runtimeFactor();
    for (const key of [...SUM_KEYS, ...MEAN_KEYS]) {
      const rows = stats[this._entities[key]] || [];
      const isSum = SUM_KEYS.includes(key);
      let j = 0;
      for (const row of rows) {
        const t = rowTime(row);
        while (j < n && t >= e0[j]) j++;
        if (j >= n) break;
        if (t < s0[j]) continue;
        const b = out[j];
        if (isSum) {
          if (isNum(row.change)) b[key] = (b[key] || 0) + row.change * (key === "runtime" ? rf : 1);
        } else if (isNum(row.mean)) {
          b[`${key}_s`] = (b[`${key}_s`] || 0) + row.mean;
          b[`${key}_n`] = (b[`${key}_n`] || 0) + 1;
          b[key] = b[`${key}_s`] / b[`${key}_n`];
        }
      }
    }
    return out;
  }

  /** Kennzahlen fuer [from, to) aus Zeilen beliebiger Aufloesung plus Tagesmitteln der Aussentemperatur. */
  _totals(stats, temps, from, to) {
    const f = from.getTime(), t = to.getTime();
    const tot = this._aggregate(stats, [from], [to])[0];
    let hdd = 0, hddDays = 0;
    for (const row of temps) {
      const s = rowTime(row);
      if (s < f || s >= t || !isNum(row.mean)) continue;
      hddDays++;
      if (row.mean < this._base) hdd += this._base - row.mean;
    }
    tot.hdd = hddDays ? hdd : null;
    // Ohne Gesamtzaehler: Summe der Teilzaehler
    if (!isNum(tot.el) && (isNum(tot.el_heat) || isNum(tot.el_dhw))) tot.el = (tot.el_heat || 0) + (tot.el_dhw || 0);
    if (!isNum(tot.th) && (isNum(tot.th_heat) || isNum(tot.th_dhw))) tot.th = (tot.th_heat || 0) + (tot.th_dhw || 0);
    return tot;
  }

  _kpis(tot) {
    return {
      el: tot.el, th: tot.th,
      az: ratio(tot.th, tot.el, MIN_EL_KWH),
      az_heat: ratio(tot.th_heat, tot.el_heat, MIN_EL_KWH),
      az_dhw: ratio(tot.th_dhw, tot.el_dhw, MIN_EL_KWH),
      dhw_share: isNum(tot.th_dhw) && isNum(tot.th) && tot.th > 0 ? (100 * tot.th_dhw) / tot.th : null,
      starts: tot.starts, runtime: tot.runtime,
      run_per_start: isNum(tot.runtime) && isNum(tot.starts) && tot.starts > 0 ? (60 * tot.runtime) / tot.starts : null,
      outdoor: tot.outdoor, hdd: tot.hdd,
      kwh_hdd: isNum(tot.hdd) && tot.hdd >= 1 ? ratio(tot.el, tot.hdd) : null,
      flow: tot.flow, cop: tot.cop,
    };
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
        return;
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
      const ids = this._ids([...SUM_KEYS, ...MEAN_KEYS]);
      const stats = (await this._stats(bStart, aEnd, ids, "day")) || {};
      if (token !== this._cmpToken) return;
      const now = Date.now();
      // Nur vollstaendige Tage: der laufende Tag zaehlt nicht
      const full = {};
      for (const [id, rows] of Object.entries(stats)) full[id] = rows.filter((row) => Number(row.end) <= now);
      const temps = full[this._entities.outdoor] || [];
      const side = (from, to) => {
        const tot = this._totals(full, temps, from, to);
        const inSide = (row) => { const rt = rowTime(row); return rt >= from.getTime() && rt < to.getTime(); };
        const elRows = (full[this._entities.el] || []).filter((row) => inSide(row) && isNum(row.change));
        const nDays = elRows.length || (full[this._entities.th] || []).filter((row) => inSide(row) && isNum(row.change)).length;
        return { tot, days: nDays };
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
      ${this._renderCompare()}
      ${this._renderChanges()}`;
  }

  _renderMain() {
    const { range: r, stats, temps } = this._data;
    const now = new Date();
    const bars = this._aggregate(stats, r.buckets, r.ends);
    const hasAny = bars.some((b) => isNum(b.el) || isNum(b.th) || isNum(b.el_heat) || isNum(b.th_heat));
    let notice = "";
    if (!hasAny) {
      if (!this._hass.states[this._entities.el]) notice = this._t("missing_entity", { id: this._entities.el });
      else if (this._since) notice = this._t("no_data_range", { since: this._date(this._since, { day: "numeric", month: "short", year: "numeric" }) });
      else notice = this._t("no_data_yet");
    } else if (this._since && this._since > r.start && r.view !== "all") {
      notice = this._t("partial_data", { since: this._date(this._since, { day: "numeric", month: "short", year: "numeric" }) });
    }
    // Kennzahlen: aktueller Zeitraum bis jetzt vs. Vorzeitraum gleicher Laenge
    const curEnd = r.end > now ? now : r.end;
    const cur = this._kpis(this._totals(stats, temps, r.start, r.end));
    let prev = null;
    if (r.prevStart) {
      const prevEnd = new Date(Math.min(r.start.getTime(), r.prevStart.getTime() + (curEnd - r.start)));
      prev = this._kpis(this._totals(stats, temps, r.prevStart, prevEnd));
    }
    this._bars = bars;
    if (!hasAny && !this._hass.states[this._entities.el]) {
      this._geom = null;
      return `<div class="msg info">${esc(notice)}</div>`;
    }
    return `
      ${notice ? `<div class="msg info">${esc(notice)}</div>` : ""}
      ${this._renderLegend()}
      <div class="chart">${this._renderChart(r, bars)}<div class="tip" hidden></div></div>
      ${this._renderKpis(cur, prev)}`;
  }

  _renderLegend() {
    const items = [
      ["el", this._t("el"), "c-elh"], ["th", this._t("th"), "c-thh"],
      ["az", this._t("az"), "c-az"], ["temp", this._t("temp"), "c-temp"],
    ];
    const sub = `<span class="sub"><i class="sw c-elh"></i>${esc(this._t("heat"))} <i class="sw c-eld"></i>${esc(this._t("dhw"))} <i class="sw c-elr"></i>${esc(this._t("rest"))}</span>`;
    return `<div class="legend">${items.map(([k, label, cls]) => `<button class="chip ${this._hidden.has(k) ? "off" : ""}" data-action="toggle" data-series="${k}" aria-pressed="${!this._hidden.has(k)}"><i class="sw ${cls} ${k === "az" || k === "temp" ? "line" : ""}"></i>${esc(label)}</button>`).join("")}${sub}</div>`;
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

    const parts = bars.map((b) => {
      const elH = isNum(b.el_heat) ? b.el_heat : 0, elD = isNum(b.el_dhw) ? b.el_dhw : 0;
      const elT = isNum(b.el) ? b.el : elH + elD;
      const thH = isNum(b.th_heat) ? b.th_heat : 0, thD = isNum(b.th_dhw) ? b.th_dhw : 0;
      const thT = isNum(b.th) ? b.th : thH + thD;
      return {
        el: [elH, elD, Math.max(0, elT - elH - elD)], elT,
        th: [thH, thD, Math.max(0, thT - thH - thD)], thT,
        az: isNum(b.el) || isNum(b.el_heat) ? ratio(thT, elT, MIN_EL_KWH) : null,
        temp: isNum(b.outdoor) ? b.outdoor : null,
      };
    });
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
    const cls = { el: ["c-elh", "c-eld", "c-elr"], th: ["c-thh", "c-thd", "c-thr"] };
    parts.forEach((p, i) => {
      const cx = left + gw * (i + 0.5);
      const stacks = [];
      if (showEl) stacks.push(["el", both ? cx - bw - 1 : cx - bw / 2]);
      if (showTh) stacks.push(["th", both ? cx + 1 : cx - bw / 2]);
      for (const [k, x] of stacks) {
        let acc = 0;
        p[k].forEach((v, j) => {
          if (!(v > 0)) return;
          const y1 = y(acc + v), y0 = y(acc);
          s += `<rect class="${cls[k][j]}" x="${x.toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0.5, y0 - y1).toFixed(1)}" rx="1"/>`;
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
    if (showAz) s += line(parts.map((p) => p.az), yAz, "c-az");
    // X-Beschriftung
    const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / (r.view === "week" ? 44 : 30)))));
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
    const az = ratio(isNum(b.th) ? b.th : (b.th_heat || 0) + (b.th_dhw || 0), isNum(b.el) ? b.el : (b.el_heat || 0) + (b.el_dhw || 0), MIN_EL_KWH);
    const row = (label, v, unit, d = 1, cls = "") => (isNum(v) ? `<tr><td>${cls ? `<i class="sw ${cls}"></i>` : ""}${esc(label)}</td><td>${this._num(v, d)}${unit ? ` ${unit}` : ""}</td></tr>` : "");
    const canDrill = { all: 1, year: 1, month: 1, week: 1 }[r.view];
    tip.innerHTML = `<div class="tt">${esc(this._bucketLabel(r.view, r.buckets[i]))}</div><table>
      ${row(`${this._t("el")} ${this._t("heat")}`, b.el_heat, "kWh", 2, "c-elh")}
      ${row(`${this._t("el")} ${this._t("dhw")}`, b.el_dhw, "kWh", 2, "c-eld")}
      ${row(`${this._t("el")}`, b.el, "kWh", 2)}
      ${row(`${this._t("th")} ${this._t("heat")}`, b.th_heat, "kWh", 2, "c-thh")}
      ${row(`${this._t("th")} ${this._t("dhw")}`, b.th_dhw, "kWh", 2, "c-thd")}
      ${row(`${this._t("th")}`, b.th, "kWh", 2)}
      ${row(this._t("az"), az, "", 2, "c-az")}
      ${row(this._t("temp"), b.outdoor, "°C", 1, "c-temp")}
      ${row(this._t("k_starts"), b.starts, "", 0)}
      ${row(this._t("k_runtime"), b.runtime, "h", 1)}
    </table>${this._tip.sticky && canDrill ? `<button class="link" data-action="drill" data-index="${i}">${esc(this._t("show"))} ›</button>` : ""}`;
    this._placeTip(tip, g.left + g.gw * (i + 0.5));
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

  _renderKpis(cur, prev) {
    // [Schluessel, Label, Einheit, Nachkommastellen, Richtung (+1 hoeher besser, -1 niedriger besser, 0 neutral), Delta absolut (K)?]
    const defs = [
      ["el", "k_el", "kWh", 1, -1], ["th", "k_th", "kWh", 1, 0],
      ["az", "k_az", "", 2, 1], ["az_heat", "k_az_heat", "", 2, 1], ["az_dhw", "k_az_dhw", "", 2, 1],
      ["dhw_share", "k_dhw_share", "%", 0, 0],
      ["starts", "k_starts", "", 0, -1], ["runtime", "k_runtime", "h", 1, 0],
      ["run_per_start", "k_run_per_start", "min", 0, 1],
      ["outdoor", "k_outdoor", "°C", 1, 0, true], ["hdd", "k_hdd", "Kd", 0, 0],
      ["kwh_hdd", "k_kwh_hdd", "kWh/Kd", 2, -1], ["flow", "k_flow", "°C", 1, 0, true],
    ];
    if (!isNum(cur.az) && isNum(cur.cop)) defs.push(["cop", "k_cop", "", 2, 0]);
    const tiles = defs.map(([k, label, unit, d, dir, abs]) => {
      const v = cur[k], p = prev ? prev[k] : null;
      let delta = "";
      if (isNum(v) && isNum(p)) {
        let txt = null, val = 0;
        if (abs) { val = v - p; txt = `${signed(val, this._num(Math.abs(val), 1))} K`; }
        else if (Math.abs(p) > 1e-9) { val = ((v - p) / Math.abs(p)) * 100; txt = `${signed(val, this._num(Math.abs(val), 0))} %`; }
        if (txt !== null) {
          const good = dir === 0 || Math.abs(val) < 0.5 ? "" : (val > 0) === (dir > 0) ? "good" : "bad";
          delta = `<span class="delta ${good}" title="${esc(this._t("vs_prev"))}: ${esc(this._num(p, d))}${unit ? ` ${esc(unit)}` : ""}">${txt}</span>`;
        }
      }
      const title = k === "hdd" || k === "kwh_hdd" ? ` title="${esc(this._t("hdd_hint", { base: this._num(this._base, 0) }))}"` : "";
      return `<div class="kpi ${isNum(v) ? "" : "empty"}"${title}><div class="kl">${esc(this._t(label))}</div>
        <div class="kv">${this._num(v, d)}${unit && isNum(v) ? `<span class="ku">${esc(unit)}</span>` : ""}</div>${delta}</div>`;
    }).join("");
    return `<div class="kpis">${tiles}</div><div class="foot">${esc(prev ? this._t("vs_prev") : this._t("vs_prev_none"))} · ${esc(this._t("hdd_hint", { base: this._num(this._base, 0) }))}</div>`;
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
          el_day: d && isNum(t.el) ? t.el / d : null,
          th_day: d && isNum(t.th) ? t.th / d : null,
          kwh_hdd: k.kwh_hdd,
          starts_day: d && isNum(t.starts) ? t.starts / d : null,
          run_per_start: k.run_per_start,
          outdoor: t.outdoor,
          flow: t.flow,
          days: d,
        };
      };
      const b = metric(c.before), a = metric(c.after);
      const defs = [
        ["az", "c_az", "", 2, 1], ["el_day", "c_el_day", "kWh", 1, -1], ["th_day", "c_th_day", "kWh", 1, 0],
        ["kwh_hdd", "c_kwh_hdd", "kWh/Kd", 2, -1], ["starts_day", "c_starts_day", "", 1, -1],
        ["run_per_start", "c_run_per_start", "min", 0, 1], ["outdoor", "c_outdoor", "°C", 1, 0, true],
        ["flow", "c_flow", "°C", 1, 0, true], ["days", "c_days", "", 0, 0, null],
      ];
      const rows = defs.map(([k, label, unit, d, dir, abs]) => {
        const vb = b[k], va = a[k];
        let delta = "–", cls = "";
        if (abs !== null && isNum(vb) && isNum(va)) {
          if (abs) { const dv = va - vb; delta = `${signed(dv, this._num(Math.abs(dv), 1))} K`; }
          else if (Math.abs(vb) > 1e-9) {
            const dv = ((va - vb) / Math.abs(vb)) * 100;
            delta = `${signed(dv, this._num(Math.abs(dv), 0))} %`;
            if (dir && Math.abs(dv) >= 0.5) cls = (dv > 0) === (dir > 0) ? "good" : "bad";
          }
        } else if (abs === null) delta = "";
        const u = unit ? ` <span class="ku">${esc(unit)}</span>` : "";
        return `<tr><td>${esc(this._t(label))}</td><td>${this._num(vb, d)}${isNum(vb) ? u : ""}</td><td>${this._num(va, d)}${isNum(va) ? u : ""}</td><td class="delta ${cls}">${delta}</td></tr>`;
      }).join("");
      const hints = [];
      if (!c.before.days && !c.after.days) hints.push(this._t("hint_nodata"));
      if (c.incomplete) hints.push(this._t("hint_incomplete", { n: c.fullAfterDays, m: c.days }));
      if (isNum(b.outdoor) && isNum(a.outdoor) && Math.abs(a.outdoor - b.outdoor) >= TEMP_HINT_K) {
        hints.push(this._t("hint_temp", { d: this._num(Math.abs(a.outdoor - b.outdoor), 1) }));
      }
      if (c.others) hints.push(this._t("hint_overlap", { n: c.others }));
      hints.push(this._t("hint_change_day"));
      body = `<table class="cmp"><thead><tr><th></th><th>${esc(this._t("before"))}</th><th>${esc(this._t("after"))}</th><th>${esc(this._t("delta"))}</th></tr></thead><tbody>${rows}</tbody></table>
        <ul class="hints">${hints.map((h, i) => `<li class="${i === hints.length - 1 ? "dim" : "warn"}">${esc(h)}</li>`).join("")}</ul>`;
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
  --esa-az: var(--success-color, #43a047);
  --esa-temp: var(--purple-color, #9c27b0);
  --esa-good: var(--success-color, #43a047);
  --esa-bad: var(--error-color, #db4437);
  --esa-warn: var(--warning-color, #ffa600);
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
.chart { position: relative; margin: 2px -4px 0; touch-action: pan-y; }
svg { display: block; overflow: visible; }
rect.c-elh { fill: var(--esa-elh); } rect.c-eld { fill: var(--esa-eld); } rect.c-elr { fill: var(--esa-elr); }
rect.c-thh { fill: var(--esa-thh); } rect.c-thd { fill: var(--esa-thd); } rect.c-thr { fill: var(--esa-thr); }
.ln { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
path.c-az { stroke: var(--esa-az); } circle.c-az { fill: var(--esa-az); }
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
.kl { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kv { font-size: 18px; font-weight: 500; margin-top: 2px; white-space: nowrap; }
.ku { font-size: 11px; font-weight: 400; color: var(--secondary-text-color); margin-left: 3px; }
.delta { font-size: 11px; color: var(--secondary-text-color); }
.delta.good { color: var(--esa-good); } .delta.bad { color: var(--esa-bad); }
.foot { font-size: 11px; color: var(--secondary-text-color); margin: 6px 2px 0; }
.msg { padding: 12px 8px; color: var(--primary-text-color); font-size: 14px; }
.msg.err { color: var(--error-color, #db4437); }
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
