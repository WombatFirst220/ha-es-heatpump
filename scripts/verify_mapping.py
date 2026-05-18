#!/usr/bin/env python3
"""
verify_mapping.py
─────────────────
Vergleicht die Werte der neuen Plugin-Entitäten (`sensor.es_hp_*`) mit den
verifizierten Multiscrape-Referenz-Sensoren (`sensor.es_wp_*`) und meldet
Abweichungen oberhalb einer konfigurierbaren Toleranz.

Nutzung
───────
    # Mit Token + Host als Argument
    python3 verify_mapping.py --host http://homeassistant.local:8123 \\
                              --token <HA_LONG_LIVED_TOKEN>

    # Oder über Umgebungsvariablen
    export HA_HOST=http://homeassistant.local:8123
    export HA_TOKEN=<long-lived-access-token>
    python3 verify_mapping.py

    # Watch-Modus (alle 30 s)
    python3 verify_mapping.py --watch 30

    # Strikte Toleranz (Standard 0.5 K / 5 %)
    python3 verify_mapping.py --abs-tol 0.2 --rel-tol 0.02

Exit-Codes
──────────
    0   – alle Werte innerhalb Toleranz
    1   – mindestens eine Abweichung über der Toleranz
    2   – Konfigurationsfehler (Host/Token fehlt, HTTP-Fehler …)

Vorbereitung
────────────
Long-Lived-Access-Token erstellen:
    Home Assistant → Profil → Sicherheit → "Langlebigen Zugriffstoken erstellen"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Mapping: Plugin-Entity  ↔  Referenz-Entity (Multiscrape oder anderer Sensor)
# ─────────────────────────────────────────────────────────────────────────────

MAPPING: list[dict] = [
    # (Plugin,                            Reference,                     abs-Tol, Bemerkung)
    dict(plugin="sensor.es_hp_aussentemp_ta",  ref="sensor.es_wp_aussentemp_ta",  abs_tol=0.5, note="Außentemperatur"),
    dict(plugin="sensor.es_hp_vorlauf_tuo",    ref="sensor.es_wp_vorlauf_tuo",    abs_tol=0.5, note="Vorlauf TUO"),
    dict(plugin="sensor.es_hp_ruecklauf_tui",  ref="sensor.es_wp_ruecklauf_tui",  abs_tol=0.5, note="Rücklauf TUI"),
    dict(plugin="sensor.es_hp_warmwasser_tw",  ref="sensor.es_wp_warmwasser_tw",  abs_tol=0.5, note="Warmwasser TW"),
    dict(plugin="sensor.es_hp_heizen",         ref="sensor.es_wp_heizen",         abs_tol=0.5, note="Heizwasser Temperatur"),
    dict(plugin="sensor.es_hp_heizen_soll",    ref="sensor.es_wp_heizen_soll",    abs_tol=0.3, note="Heizen Sollwert"),
    dict(plugin="sensor.es_hp_frequenz_hz",    ref="sensor.es_wp_frequenz_hz",    abs_tol=1.0, note="Kompressor Frequenz"),
    dict(plugin="sensor.es_hp_heissgas_td",    ref="sensor.es_wp_heissgas_td",    abs_tol=1.0, note="Heißgastemperatur"),
    dict(plugin="sensor.es_hp_spreizung",      ref="sensor.es_wp_spreizung",      abs_tol=0.3, note="Spreizung (Δ T)"),
]


# ─────────────────────────────────────────────────────────────────────────────
# HA REST API helpers
# ─────────────────────────────────────────────────────────────────────────────

class HAClient:
    def __init__(self, host: str, token: str) -> None:
        self.host = host.rstrip("/")
        self.token = token

    def get_state(self, entity_id: str) -> tuple[str | None, dict]:
        """Return (state, attributes). Returns (None, {}) on 404 or error."""
        url = f"{self.host}/api/states/{entity_id}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("state"), data.get("attributes", {})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, {}
            raise
        except Exception:
            return None, {}


# ─────────────────────────────────────────────────────────────────────────────
# Comparison logic
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    plugin_id: str
    ref_id: str
    plugin_val: str | None
    ref_val: str | None
    unit: str
    note: str
    abs_tol: float
    delta: float | None
    severity: str   # "ok" | "warn" | "mismatch" | "skipped"

    @property
    def symbol(self) -> str:
        return {"ok": "✓", "warn": "~", "mismatch": "✗", "skipped": "·"}[self.severity]


def _as_float(s: str | None) -> float | None:
    if s in (None, "unknown", "unavailable", ""):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def compare(client: HAClient, abs_tol_override: float | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for m in MAPPING:
        pval, pattrs = client.get_state(m["plugin"])
        rval, rattrs = client.get_state(m["ref"])
        unit = pattrs.get("unit_of_measurement") or rattrs.get("unit_of_measurement") or ""

        pf = _as_float(pval)
        rf = _as_float(rval)

        abs_tol = abs_tol_override if abs_tol_override is not None else m["abs_tol"]

        if pval is None and rval is None:
            sev = "skipped"
            delta = None
        elif pval is None:
            sev = "skipped"   # plugin entity nicht vorhanden — vermutlich noch nicht migriert
            delta = None
        elif rval is None:
            sev = "skipped"   # ref entity nicht vorhanden — User hat Multiscrape evtl. schon entfernt
            delta = None
        elif pf is None or rf is None:
            sev = "warn"      # nicht-numerischer State
            delta = None
        else:
            delta = pf - rf
            if abs(delta) <= abs_tol:
                sev = "ok"
            elif abs(delta) <= 2 * abs_tol:
                sev = "warn"
            else:
                sev = "mismatch"

        results.append(
            CheckResult(
                plugin_id=m["plugin"],
                ref_id=m["ref"],
                plugin_val=pval,
                ref_val=rval,
                unit=unit,
                note=m["note"],
                abs_tol=abs_tol,
                delta=delta,
                severity=sev,
            )
        )
    return results


def _fmt_val(v: str | None, unit: str) -> str:
    if v is None:
        return "—"
    if v in ("unknown", "unavailable"):
        return v
    try:
        return f"{float(v):7.2f} {unit}".rstrip()
    except (ValueError, TypeError):
        return f"{v} {unit}".strip()


def render_report(results: list[CheckResult]) -> str:
    lines = []
    lines.append("=" * 92)
    lines.append(f"ES Heatpump – Mapping Verification  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 92)
    lines.append(f"{'':<2} {'Beschreibung':<24} {'Plugin':<14} {'Referenz':<14} {'Δ':>10} {'Toleranz':>10}")
    lines.append("─" * 92)

    counts = {"ok": 0, "warn": 0, "mismatch": 0, "skipped": 0}
    for r in results:
        counts[r.severity] += 1
        plugin_short = r.plugin_id.replace("sensor.es_hp_", "es_hp_")
        ref_short = r.ref_id.replace("sensor.es_wp_", "es_wp_")
        delta_str = f"{r.delta:+.2f}" if r.delta is not None else "—"
        unit = r.unit
        lines.append(
            f"{r.symbol:<2} "
            f"{r.note:<24} "
            f"{_fmt_val(r.plugin_val, unit):<14} "
            f"{_fmt_val(r.ref_val, unit):<14} "
            f"{delta_str:>10} "
            f"{r.abs_tol:>9.2f}"
        )

    lines.append("─" * 92)
    lines.append(
        f"Summary:  ✓ {counts['ok']} OK    ~ {counts['warn']} Warn    "
        f"✗ {counts['mismatch']} Mismatch    · {counts['skipped']} skipped"
    )
    lines.append("=" * 92)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifiziert Plugin-Werte gegen Multiscrape-Referenzen."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HA_HOST", "http://homeassistant.local:8123"),
        help="HA Base-URL (Default: $HA_HOST oder http://homeassistant.local:8123)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HA_TOKEN"),
        help="Long-Lived-Access-Token (Default: $HA_TOKEN)",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=None,
        help="Absolute Toleranz (überschreibt alle Mapping-Defaults)",
    )
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECS",
        help="Im Schleifenmodus jede N Sekunden neu prüfen (Ctrl-C zum Beenden)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Ergebnis als JSON ausgeben statt formatierter Tabelle",
    )
    args = parser.parse_args()

    if not args.token:
        print("FEHLER: Kein Token angegeben (--token oder $HA_TOKEN).", file=sys.stderr)
        return 2

    client = HAClient(args.host, args.token)

    def run_once() -> int:
        try:
            results = compare(client, abs_tol_override=args.abs_tol)
        except urllib.error.URLError as e:
            print(f"FEHLER: HA nicht erreichbar ({e}).", file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps([{
                "plugin": r.plugin_id, "ref": r.ref_id,
                "plugin_val": r.plugin_val, "ref_val": r.ref_val,
                "delta": r.delta, "severity": r.severity, "note": r.note,
                "abs_tol": r.abs_tol,
            } for r in results], indent=2, ensure_ascii=False))
        else:
            print(render_report(results))

        has_mismatch = any(r.severity == "mismatch" for r in results)
        return 1 if has_mismatch else 0

    if args.watch:
        try:
            while True:
                exit_code = run_once()
                print(f"\n(nächste Prüfung in {args.watch} s, Ctrl-C zum Beenden)\n")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nBeendet.")
            return 0
    else:
        return run_once()


if __name__ == "__main__":
    sys.exit(main())
