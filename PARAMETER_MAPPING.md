# ES Heatpump – Verifiziertes Parameter-Mapping

**Stand:** 2026-05-18
**Methode:** Pearson-Korrelation der Plugin-`parXX`-Sensoren gegen die verifizierten Multiscrape-Sensoren (`sensor.es_wp_*`) im Heizzyklus 2026-05-17 18:00–18:30.
**Datenpunkte:** ~30 pro Sensor (10-Sek-Auflösung während Kompressor-Hochlauf).

## Verifiziertes Mapping (hohe Konfidenz)

| par | Bedeutung | r (Korrel.) | MAD | Quelle der Wahrheit |
|---|---|---|---|---|
| **par4** | Vorlauftemperatur Tuo | +0.958 | 1.00 | `es_wp_vorlauf_tuo` |
| **par5** | Rücklauftemperatur Tui | +0.951 | 0.81 | `es_wp_ruecklauf_tui` |
| **par6** | Heizen Solltemperatur | — | 0.00 | Snapshot identisch |
| **par7** | Warmwasser Ist (Tw) | — | 0.00 | Snapshot identisch |
| **par8** | Heizwasser-Temperatur (vor Mischer) | +0.981 | 0.38 | `es_wp_heizen` |
| **par9** | Mischventil 1 Temperatur | — | — | nur dieser Sensor liefert Wert |
| **par10** | Mischventil 2 Temperatur (–99 = n/a) | — | — | konstant –99, nicht angeschlossen |
| **par11** | Raumtemperatur (TR) | — | — | nur dieser Sensor liefert Wert |
| **par15** | Betriebsmodus (1=Heizen, 0=Aus) | — | — | binäres Signal |
| **par20** | **Kompressor Frequenz Hz** | +0.983 | 3.53 | `es_wp_frequenz_hz` |
| **par24** | Außentemperatur (Ta) | +1.000 | 0.02 | `es_wp_aussentemp_ta` |
| **par25** | **Heißgastemperatur (Td)** ⚡ NEU | +0.998 | 0.35 | `es_wp_heissgas_td` |
| **par31** | Spannung (V) | — | — | konstant ~231V |
| **par37** | Software Version | — | — | konstant 218 |
| **par41** | AH Betriebszeit (min) | — | — | Counter (monoton steigend) |
| **par42** | HBH Betriebszeit (min) | — | — | Counter |
| **par43** | HWTBH Betriebszeit (min) | — | — | Counter (0 = nicht genutzt) |

## Korrektur gegenüber aktuellem Code (`const.py`)

| par | Aktuell falsch | Verifiziert korrekt | Beleg |
|---|---|---|---|
| **par25** | `"Temperatur par25"` (unbekannt) | **Heißgastemperatur (Td)** | r=+0.998 mit `es_wp_heissgas_td`, MAD=0.35 °C |
| **par21** | `"Lüfter Drehzahl"` (rpm) | **NICHT Lüfter** – wahrscheinlich Kompressor-Sollwert oder berechnete Drehzahl | par21 bleibt im Leerlauf bei 200, Lüfter ist 0; Werte 200–334 statt 0–622 |
| **par26** | `"Leistungsaufnahme"` (kW, Wert 22 kW physikalisch unmöglich) | **Temperatur** (vermutl. Niederdruck/Verdampfung) – fällt während Kompressor-Betrieb von 22→4 | r=–0.955 mit Hochdruck (inverse Korrel.), MAD zu Strom nicht stimmig |
| **par27** | `"Pumpe P0 Status"` (sollte 0/1 sein) | **Kontinuierliche Temperatur** (vermutl. Verdampfung Te) – fällt 14.8→1.4 während Operation | Werte nicht binär; r=–0.921 mit Hochdruck |
| **par33** | `"Pumpe P1 Status"` | unverifizierbar, **streichen** | konstant 0 in den Daten |
| **par34** | `"Pumpe P2 Status"` | unverifizierbar, **streichen** | konstant 1, kein Bezug zu echtem Pumpenstatus |
| **par28** | `"Energie gesamt"` (kWh) | **streichen** – keine plausible Energie-Treppe nachgewiesen | Wert 0.0 dauerhaft, Energie kommt aus Shelly |
| **par38** | `"Kompressor Drehzahl berechnet"` | **streichen** – Wert konstant 2.0, kein Mehrwert | |

## Vermutliche, aber nicht eindeutig zugewiesene Parameter

Diese korrelieren mit dem Heizzyklus, lassen sich aber keiner Multiscrape-Größe eindeutig zuordnen → ins Plugin nur als **Diagnose-Sensoren** (default disabled), Name neutral lassen:

| par | Verhalten | Vermutung |
|---|---|---|
| par22 | 11°C idle → steigt auf ~20°C während Op | Kondensationstemperatur Tc oder Sammler-Temp |
| par23 | 11°C idle → fällt auf ~6.7°C während Op | Sauggastemperatur Ts |
| par26 | 22°C idle → fällt auf ~4°C während Op | Niederdruck-Sättigung / Verdampfungstemperatur |
| par27 | 15°C idle → fällt auf ~1.4°C während Op | Verdampfungstemperatur Te |
| par39 | 8°C idle → fällt auf ~1°C während Op | Saugleitung außen / Te ähnlich |
| par40 | 9°C idle → V-Form –3°C → +28°C | Berechnete Differenz (vermutl. Überhitzung) |

## Parameter ohne erkennbaren Wert → KOMPLETT WEGLASSEN

`par1, par2, par3, par12, par13, par14, par16, par17, par18, par19, par29, par30, par32, par35, par36, par44–par100`
→ alle dauerhaft 0.0, kein erkennbares Muster. **Im Plugin gar nicht erst als Entität anlegen.**

## Lüfter-Drehzahl: NICHT in der API verfügbar

Keine der getesteten `parXX`-Größen entspricht der echten Lüfter-Drehzahl (`es_wp_luefter_f1`, 0–622 rpm). Die Multiscrape liest „F1" vermutlich aus der HTML-Detailseite, die nicht im `/realdata/get`-Endpunkt enthalten ist.

→ **Empfehlung:** Lüfter-Sensor aus Plugin **streichen**, oder im Plugin eine zweite API-Route ergänzen, die die Detailseite abruft. Im manuellen Dashboard kann der bestehende Multiscrape-Sensor zunächst weiter genutzt werden.

## Berechnete Sensoren (im neuen Plugin)

| Neuer Sensor | Berechnung |
|---|---|
| `Spreizung` | `par4 – par5` (Vorlauf – Rücklauf) |
| `Aktueller COP` | `(par4 – par5) × Volumenstrom × cp_Wasser / Shelly_Power_W`. Vereinfacht: Auto-Berechnung deaktiviert, wenn Shelly fehlt. |
| `Thermische Leistung` | `(par4 – par5) × Wasser-Durchfluss × 1.16 kWh/(m³·K)` (Standard-Annahme für Volumenstrom konfigurierbar) |

Volumenstrom (m³/h) wird zunächst als statischer Parameter im Config-Flow gesetzt (Default: 1.2 m³/h für AW12-R32 typisch), später optional ein verlinkter Volumenstromsensor.

---

## Slug-Mapping für Entity-IDs (Präfix `es_hp_`)

Diese Slugs werden via `_attr_suggested_object_id` an HA übergeben, damit die finalen Entity-IDs konsistent benannt sind:

| par | Slug → entity_id |
|---|---|
| par4 | `sensor.es_hp_vorlauf_tuo` |
| par5 | `sensor.es_hp_ruecklauf_tui` |
| par6 | `sensor.es_hp_heizen_soll` |
| par7 | `sensor.es_hp_warmwasser_tw` |
| par8 | `sensor.es_hp_heizen` |
| par9 | `sensor.es_hp_mischventil_1` |
| par10 | `sensor.es_hp_mischventil_2` |
| par11 | `sensor.es_hp_raumtemperatur` |
| par15 | `sensor.es_hp_betriebsart` |
| par20 | `sensor.es_hp_frequenz_hz` |
| par24 | `sensor.es_hp_aussentemp_ta` |
| par25 | `sensor.es_hp_heissgas_td` |
| par31 | `sensor.es_hp_spannung` |
| par37 | `sensor.es_hp_software_version` |
| par41 | `sensor.es_hp_ah_betriebszeit` |
| par42 | `sensor.es_hp_hbh_betriebszeit` |
| par43 | `sensor.es_hp_hwtbh_betriebszeit` |
| par22 | `sensor.es_hp_diag_par22` (diagnostic, disabled by default) |
| par23 | `sensor.es_hp_diag_par23` |
| par26 | `sensor.es_hp_diag_par26` |
| par27 | `sensor.es_hp_diag_par27` |
| par39 | `sensor.es_hp_diag_par39` |
| par40 | `sensor.es_hp_diag_par40` |
| par21 | `sensor.es_hp_diag_par21` |
| (berechnet) | `sensor.es_hp_spreizung` |
| (berechnet) | `sensor.es_hp_thermische_leistung` |
| (berechnet) | `sensor.es_hp_aktueller_cop` |
