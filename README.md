# ES Heatpump – Home Assistant HACS Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.4.0-green.svg)](https://github.com/WombatFirst220/ha-es-heatpump/releases)

---

> 🇩🇪 [Deutsche Version](#deutsch) · 🇬🇧 [English Version](#english) · 📋 [Changelog](#changelog)

---

<a name="deutsch"></a>
## 🇩🇪 Deutsch

Home Assistant Integration für **Energy Save Wärmepumpen** über das [myheatpump.com](https://www.myheatpump.com) Portal.  
Automatische Anmeldung, Session-Verwaltung, Sensor-Erstellung und **vollautomatische Dashboard-Installation** – keine manuelle YAML-Konfiguration nötig.

### ✨ Features

| Feature | Beschreibung |
|---------|-------------|
| 🔐 Automatischer Login | Zugangsdaten einmal eingeben – alles andere übernimmt die Integration |
| 🔄 Session-Verwaltung | Automatische Erneuerung der Session (alle 55 Minuten) ohne Neustart |
| 🔍 Automatische Geräteerkennung | `mn` und `devid` werden automatisch vom Portal abgerufen |
| 📊 Alle Sensoren | 40+ Parameter, 14 davon mit verifizierten Klarnamen |
| 📋 Dashboard | „ES Heatpump"-Dashboard wird **automatisch** installiert und in der Seitenleiste angezeigt |
| ⚙️ Konfigurierbar | Abfrageintervall (10–3600 s) und Portal-URL anpassbar |
| 🌍 Mehrsprachig | UI auf Deutsch und Englisch |

### 📦 Installation via HACS

1. **HACS öffnen** → Integrationen → ⋮ (drei Punkte) → **Benutzerdefinierte Repositories**
2. URL eingeben: `https://github.com/WombatFirst220/ha-es-heatpump`  
   Kategorie: **Integration**
3. Integration suchen: **ES Heatpump** → **Herunterladen**
4. **Home Assistant neu starten**

### ⚡ Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**
2. Suche nach **ES Heatpump**
3. Zugangsdaten eingeben:

   | Feld | Beschreibung |
   |------|-------------|
   | Benutzername | E-Mail-Adresse beim myheatpump.com Portal |
   | Passwort | Dein Passwort |
   | Portal-URL | Standard: `https://www.myheatpump.com` |
   | Aktualisierungsintervall | Sekunden zwischen den Abfragen (Standard: 60) |

4. ✅ Alle Sensoren werden automatisch angelegt
5. ✅ Das Dashboard **„ES Heatpump"** erscheint automatisch in der Seitenleiste

> **Hinweis:** Beim ersten Setup schreibt HA die Dashboard-Registrierung in den Lovelace-Storage.  
> Falls das Dashboard nicht sofort erscheint, reicht ein einmaliger **HA-Neustart**.

### 📋 Dashboard

Das Dashboard wird vollautomatisch installiert und enthält:

- **Temperaturen** – Außen, Vorlauf, Rücklauf, Warmwasser, Mischventile, Raumtemperatur
- **Temperaturverlauf (24h)** – History Graph
- **Betrieb & Leistung** – Betriebsmodus, Kompressor, Lüfter, Pumpen
- **Spannung & Energie** – Netzspannung, Leistungsaufnahme, Energiezähler
- **Betriebszeiten** – AH, HBH, HWTBH Betriebszeit in Minuten
- **Energiebilanz-View** – Balkendiagramme (14 Tage)

### 🌡️ Bekannte Sensoren

#### ✅ Verifizierte Parameter (Live-Messung bestätigt)

| Parameter | Name | Einheit | Bestätigung |
|-----------|------|---------|-------------|
| par6  | Heizen Solltemperatur | °C | Portal „Set Temperature" |
| par7  | Warmwasser Ist | °C | Portal „Sanitary Hot Water Temp. TW" |
| par8  | Heizkreis Temperatur | °C | Portal „Cooling/Heating Water Temp. TC" |
| par9  | Mischventil 1 Temperatur | °C | Portal „Water Temp. After Mixing Valve 1" |
| par10 | Mischventil 2 Temperatur | °C | Portal „Water Temp. After Mixing Valve 2" |
| par11 | Raumtemperatur | °C | Portal „Room Temp. TR" |
| par15 | Betriebsmodus | – | Portal „Unit Current Working Mode" (1=Heizen) |
| par20 | Kompressor Frequenz | Hz | Portal „Comp. Speed Hz" |
| par24 | Außentemperatur | °C | Portal „Actual Ambient Temp. Ta" |
| par31 | Spannung | V | Portal „Voltage" |
| par37 | Software Version | – | Portal „Software Version" |
| par38 | Kompressor Drehzahl berechnet | – | Portal „Calculated Comp. Speed" |
| par41 | AH Betriebszeit | min | Portal „AH Working Time" |
| par42 | HBH Betriebszeit | min | Portal „HBH Working Time" |

#### ~ Plausible Parameter (noch nicht abschließend bestätigt)

| Parameter | Name | Einheit | Hinweis |
|-----------|------|---------|---------|
| par4  | Vorlauftemperatur | °C | Wert 35.1 plausibel |
| par5  | Rücklauftemperatur | °C | Wert 33.6 plausibel |
| par21 | Lüfter Drehzahl | rpm | Wert 400.0 plausibel |
| par26 | Leistungsaufnahme | kW | Wert 1.8 plausibel |
| par28 | Energie gesamt | kWh | Wert 560.0 |
| par43 | HWTBH Betriebszeit | min | Wert 0 (kalt) |

#### ❓ Unbekannte Parameter (werden als `Parameter parXX` angelegt)

par1, par2, par3, par12, par13, par14, par16–par19, par23, par25, par27, par29, par30, par32–par36, par39, par40, par44–par48

> Bitte ein **GitHub Issue** eröffnen, wenn du einen dieser Parameter identifiziert hast!  
> Je mehr Nutzer Rückmeldungen geben, desto vollständiger wird das Mapping.

### 🔧 Erweiterte Konfiguration (für Entwickler)

Abweichende Endpunkte lassen sich in `const.py` anpassen:

```python
LOGIN_PATH        = "/a/login"
DEVICE_LIST_PATH  = "/a/amt/deviceList/listData"
REALDATA_PATH     = "/a/amt/realdata/get"
```

### 🐛 Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| „Anmeldung fehlgeschlagen" | Zugangsdaten im Portal prüfen |
| Keine Sensordaten | HA-Logs prüfen (`Einstellungen → System → Logs`) |
| Dashboard fehlt | HA einmal neu starten |
| Sensoren `unavailable` | Netzwerkverbindung und Portal-Erreichbarkeit prüfen |
| Sensor hat falschen Namen | GitHub Issue mit par-ID, Portalname und aktuellem Wert öffnen |

---

<a name="english"></a>
## 🇬🇧 English

Home Assistant integration for **Energy Save heat pumps** via the [myheatpump.com](https://www.myheatpump.com) portal.  
Automatic login, session management, sensor creation, and **fully automatic dashboard installation** – no manual YAML configuration required.

### ✨ Features

| Feature | Description |
|---------|-------------|
| 🔐 Automatic Login | Enter credentials once – the integration handles everything else |
| 🔄 Session Management | Automatic session renewal (every 55 minutes) without restarts |
| 🔍 Automatic Device Discovery | `mn` and `devid` are fetched automatically from the portal |
| 📊 All Sensors | 40+ parameters, 14 confirmed with friendly names |
| 📋 Dashboard | The "ES Heatpump" dashboard is **automatically** installed and shown in the sidebar |
| ⚙️ Configurable | Poll interval (10–3600 s) and portal URL adjustable |
| 🌍 Multilingual | UI available in German and English |

### 📦 Installation via HACS

1. **Open HACS** → Integrations → ⋮ (three dots) → **Custom Repositories**
2. Enter URL: `https://github.com/WombatFirst220/ha-es-heatpump`  
   Category: **Integration**
3. Search for **ES Heatpump** → **Download**
4. **Restart Home Assistant**

### ⚡ Setup

1. **Settings → Devices & Services → Add Integration**
2. Search for **ES Heatpump**
3. Enter your credentials:

   | Field | Description |
   |-------|-------------|
   | Username | E-mail address for the myheatpump.com portal |
   | Password | Your password |
   | Portal URL | Default: `https://www.myheatpump.com` |
   | Update interval | Seconds between polls (default: 60) |

4. ✅ All sensors are created automatically
5. ✅ The **"ES Heatpump"** dashboard appears automatically in the sidebar

> **Note:** On first setup HA writes the dashboard registration to the Lovelace storage.  
> If the dashboard does not appear immediately, a single **HA restart** will make it visible.

### 📋 Dashboard

The dashboard is installed automatically and includes:

- **Temperatures** – Outdoor, flow, return, hot water, mixing valves, room temperature
- **Temperature history (24h)** – History graph
- **Operation & Power** – Operating mode, compressor, fan, pumps
- **Voltage & Energy** – Mains voltage, power consumption, energy counters
- **Operating hours** – AH, HBH, HWTBH runtimes in minutes
- **Energy balance view** – Bar charts (14 days)

### 🌡️ Known Sensors

#### ✅ Verified Parameters (confirmed by live measurement)

| Parameter | Name | Unit | Confirmed by |
|-----------|------|------|-------------|
| par6  | Heating setpoint temperature | °C | Portal "Set Temperature" |
| par7  | Hot water actual | °C | Portal "Sanitary Hot Water Temp. TW" |
| par8  | Heating circuit temperature | °C | Portal "Cooling/Heating Water Temp. TC" |
| par9  | Mixing valve 1 temperature | °C | Portal "Water Temp. After Mixing Valve 1" |
| par10 | Mixing valve 2 temperature | °C | Portal "Water Temp. After Mixing Valve 2" |
| par11 | Room temperature | °C | Portal "Room Temp. TR" |
| par15 | Operating mode | – | Portal "Unit Current Working Mode" (1=Heating) |
| par20 | Compressor frequency | Hz | Portal "Comp. Speed Hz" |
| par24 | Outdoor temperature | °C | Portal "Actual Ambient Temp. Ta" |
| par31 | Voltage | V | Portal "Voltage" |
| par37 | Software version | – | Portal "Software Version" |
| par38 | Calculated compressor speed | – | Portal "Calculated Comp. Speed" |
| par41 | AH operating time | min | Portal "AH Working Time" |
| par42 | HBH operating time | min | Portal "HBH Working Time" |

#### ~ Plausible Parameters (not yet fully confirmed)

| Parameter | Name | Unit | Note |
|-----------|------|------|------|
| par4  | Flow temperature | °C | Value 35.1 plausible |
| par5  | Return temperature | °C | Value 33.6 plausible |
| par21 | Fan speed | rpm | Value 400.0 plausible |
| par26 | Power consumption | kW | Value 1.8 plausible |
| par28 | Total energy | kWh | Value 560.0 |
| par43 | HWTBH operating time | min | Value 0 (cold) |

#### ❓ Unknown Parameters (shown as `Parameter parXX`)

par1, par2, par3, par12, par13, par14, par16–par19, par23, par25, par27, par29, par30, par32–par36, par39, par40, par44–par48

> Please open a **GitHub issue** if you have identified any of these parameters!  
> The more users contribute, the more complete the mapping becomes.

### 🔧 Advanced Configuration (for developers)

If your installation uses different endpoints, adjust `const.py`:

```python
LOGIN_PATH        = "/a/login"
DEVICE_LIST_PATH  = "/a/amt/deviceList/listData"
REALDATA_PATH     = "/a/amt/realdata/get"
```

### 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Login failed" | Check credentials on the myheatpump.com portal |
| No sensor data | Check HA logs (`Settings → System → Logs`) |
| Dashboard missing | Restart HA once |
| Sensors `unavailable` | Check network connectivity and portal availability |
| Sensor has wrong name | Open a GitHub issue with par-ID, portal label, and current value |

---

## 📁 Repository Structure

```
ha-es-heatpump/
├── hacs.json
├── README.md
├── custom_components/es_heatpump/
│   ├── __init__.py              # Integration setup & teardown + dashboard trigger
│   ├── manifest.json            # HA integration manifest
│   ├── const.py                 # Verified parameter mapping
│   ├── coordinator.py           # Login → device discovery → sensor polling
│   ├── config_flow.py           # UI setup wizard
│   ├── sensor.py                # Sensor entities
│   ├── dashboard.py             # Auto-dashboard installer/remover
│   ├── strings.json             # UI labels
│   ├── translations/
│   │   ├── de.json              # German
│   │   └── en.json              # English
│   └── dashboard/
│       └── es_heatpump.yaml     # Bundled Lovelace dashboard
└── dashboards/
    └── es_heatpump.yaml         # Same file – for manual install fallback
```

---

<a name="changelog"></a>
## 📋 Changelog

---

### v1.4.0 – Dashboard-Installation zuverlässig / Dashboard install reliable
*2026-03-20*

**🇩🇪**
- **Fix: Dashboard erscheint jetzt zuverlässig in der Seitenleiste** ohne manuellen Neustart
-  komplett neu geschrieben: schreibt jetzt direkt in  (exakt das Format das HA selbst verwendet) statt über die interne Lovelace-Collection-API
- Dreistu­figer Lovelace-Reload nach der Installation:  → -Event →  (Fallback-Kette)
- : Dashboard-Installation läuft jetzt synchron () statt als Hintergrund-Task – verhindert Race-Conditions beim HA-Start
- Persistent Notification erscheint nur noch als letzter Fallback, wenn alle Reload-Methoden fehlschlagen

**🇬🇧**
- **Fix: Dashboard now reliably appears in the sidebar** without a manual restart
-  completely rewritten: now writes directly to  (the exact format HA itself uses) instead of going through the internal Lovelace collection API
- Three-step Lovelace reload after installation:  →  event →  (fallback chain)
- : dashboard installation now runs synchronously () instead of as a background task – prevents race conditions on HA startup
- Persistent notification now only shown as a last resort if all reload methods fail

---

### v1.3.0 – Parameter-Mapping verifiziert / Parameter mapping verified
*2026-03-20*

**🇩🇪**
- **14 Parameter live bestätigt** durch direkten Vergleich der Portal-Anzeige mit den par-Rohwerten über Chrome DevTools
- Korrektes Mapping für: Außentemperatur (par24), Warmwasser (par7), Heizkreis (par8), Mischventile (par9/par10), Raumtemperatur (par11), Solltemperatur (par6), Betriebsmodus (par15), Kompressor-Frequenz (par20), Spannung (par31), Software-Version (par37), Kompressor-Drehzahl (par38), AH/HBH-Betriebszeiten (par41/par42)
- Alle unbekannten Parameter werden weiterhin als `Parameter parXX` angelegt – kein Datenverlust
- Kommentare im Code markieren verifizierte (✓), plausible (~) und unbekannte (?) Parameter

**🇬🇧**
- **14 parameters verified live** by cross-referencing portal UI values against raw par values via Chrome DevTools
- Correct mapping for: outdoor temperature (par24), hot water (par7), heating circuit (par8), mixing valves (par9/par10), room temperature (par11), setpoint (par6), operating mode (par15), compressor frequency (par20), voltage (par31), software version (par37), compressor speed (par38), AH/HBH runtimes (par41/par42)
- All unknown parameters are still created as `Parameter parXX` – no data loss
- Code comments mark verified (✓), plausible (~), and unknown (?) parameters

---

### v1.2.0 – Korrekter Daten-Endpunkt / Correct data endpoint
*2026-03-20*

**🇩🇪**
- **Kritischer Fix:** Daten-Endpunkt korrigiert von `/a/amt/desktop/load` → `/a/amt/realdata/get`
- Neuer dreistufiger API-Flow: Login → Geräteerkennung → Sensordaten
- **Automatische Geräteerkennung:** `mn` und `devid` werden nach dem Login automatisch über `POST /a/amt/deviceList/listData` abgerufen – keine manuelle Eingabe nötig
- `_normalize()` vereinfacht: Response ist flaches JSON mit par-Werten direkt auf oberster Ebene

**🇬🇧**
- **Critical fix:** Data endpoint corrected from `/a/amt/desktop/load` → `/a/amt/realdata/get`
- New three-step API flow: login → device discovery → sensor data
- **Automatic device discovery:** `mn` and `devid` are fetched automatically after login via `POST /a/amt/deviceList/listData` – no manual input required
- `_normalize()` simplified: response is flat JSON with par values directly at top level

---

### v1.1.0 – Login-Erkennung korrigiert / Login detection fixed
*2026-03-20*

**🇩🇪**
- **Kritischer Fix:** Portal antwortet auf erfolgreichen Login mit `{"msg": "Login successful!"}` statt `{"success": true}` – die Erkennung wurde entsprechend angepasst
- Alle drei Erfolgs-Formate werden nun erkannt: `success: true`, `code: 0/200` und `"success" im msg-Text`
- Fehlermeldung im Log war irreführend: „login failed – portal response: Login successful!" – behoben

**🇬🇧**
- **Critical fix:** Portal responds to successful login with `{"msg": "Login successful!"}` instead of `{"success": true}` – detection updated accordingly
- All three success formats now handled: `success: true`, `code: 0/200`, and `"success"` in msg text
- Misleading log message fixed: "login failed – portal response: Login successful!"

---

### v1.0.0 – Erstveröffentlichung / Initial release
*2026-03-20*

**🇩🇪**
- Erste vollständige HACS-Integration für Energy Save Wärmepumpen via myheatpump.com
- Config Flow UI: Einrichtung über HA-Oberfläche ohne YAML
- Base64-kodierte Anmeldedaten (vom Portal so gefordert)
- Korrekte Login-Endpunkte durch Browser-DevTools verifiziert: `POST /a/login`
- Pflichtfelder `validCode`, `loginValidCode`, `__url` (leer) im Login-Payload enthalten
- Session-Verwaltung mit automatischer Erneuerung nach 55 Minuten
- Lovelace-Dashboard „ES Heatpump" wird automatisch installiert (mit Fallback auf Storage + Restart-Hinweis)
- Dashboard wird beim Entfernen der Integration automatisch wieder gelöscht
- Übersetzungen: Deutsch und Englisch
- Options Flow: Abfrageintervall und Portal-URL nachträglich änderbar

**🇬🇧**
- First full HACS integration for Energy Save heat pumps via myheatpump.com
- Config Flow UI: setup via HA interface without any YAML
- Base64-encoded credentials (required by the portal)
- Correct login endpoints verified via browser DevTools: `POST /a/login`
- Required fields `validCode`, `loginValidCode`, `__url` (empty) included in login payload
- Session management with automatic renewal after 55 minutes
- Lovelace dashboard "ES Heatpump" installed automatically (with fallback to storage + restart notice)
- Dashboard is automatically removed when the integration is deleted
- Translations: German and English
- Options Flow: poll interval and portal URL can be changed after setup

---

## 📄 License

MIT – Contributions welcome! 🎉  
If this integration helps you, a ⭐ on GitHub is appreciated!
