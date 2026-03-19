# ES Heatpump – Home Assistant HACS Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

> 🇩🇪 [Deutsche Version](#deutsch) · 🇬🇧 [English Version](#english)

---

<a name="deutsch"></a>
## 🇩🇪 Deutsch

Home Assistant Integration für **Energy Save Wärmepumpen** über das [myheatpump.com](https://www.myheatpump.com) Portal.  
Automatische Anmeldung, Session-Verwaltung, Sensor-Erstellung und **vollautomatische Dashboard-Installation** – keine manuelle YAML-Konfiguration nötig.

### ✨ Features

| Feature | Beschreibung |
|---------|-------------|
| 🔐 Automatischer Login | Zugangsdaten einmal eingeben – alles andere übernimmt die Integration |
| 🔄 Session-Verwaltung | Automatische Erneuerung der Session ohne Neustart |
| 📊 Alle Sensoren | 34+ bekannte Parameter mit deutschen Klarnamen, Einheit und Device Class |
| 🔍 Unbekannte Parameter | Neue Parameter werden als `Parameter parXX` angelegt – kein Datenverlust |
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

- **Temperaturen** – Außen, Vorlauf, Rücklauf, Warmwasser (Ist/Soll)
- **Temperaturverlauf (24h)** – History Graph
- **Betrieb & Leistung** – Betriebsmodus, Kompressor, Lüfter, Pumpen, COP
- **Kältekreis** – Sauggas, Heißgas, Druck
- **Energie gesamt** – Wärme & Strom für Heizen und Warmwasser
- **Heizkurve & Einstellungen** – Steilheit, Parallelverschiebung, Sollwerte
- **Betriebsstunden** – Kompressor, Heizen, Warmwasser, Starts
- **Energiebilanz-View** – Balkendiagramme (14 Tage)

### 🌡️ Bekannte Sensoren

| Parameter | Name | Einheit |
|-----------|------|---------|
| par1 | Außentemperatur | °C |
| par2 | Vorlauftemperatur | °C |
| par3 | Rücklauftemperatur | °C |
| par4 | Warmwasser Ist | °C |
| par5 | Warmwasser Soll | °C |
| par6 | Vorlauf Soll | °C |
| par7 | Sauggastemperatur | °C |
| par8 | Heißgastemperatur | °C |
| par9 | Kondensationstemperatur | °C |
| par10 | Verdampfungstemperatur | °C |
| par11 | Kältemittel Hochdruck | bar |
| par12 | Kältemittel Niederdruck | bar |
| par13 | Leistungsaufnahme | kW |
| par14 | Heizleistung | kW |
| par15 | COP (Arbeitszahl) | – |
| par16 | Energie Heizen gesamt | kWh |
| par17 | Energie Warmwasser gesamt | kWh |
| par18 | Strom Heizen gesamt | kWh |
| par19 | Strom Warmwasser gesamt | kWh |
| par20 | Betriebsmodus | – |
| par21 | Kompressor Frequenz | Hz |
| par22 | Lüfter Drehzahl | rpm |
| par23 | Pumpe Heizkreis | % |
| par24 | Pumpe Warmwasser | % |
| par30 | Heizkurve Steilheit | – |
| par31 | Heizkurve Parallelverschiebung | K |
| par35 | Heizen Einschalttemperatur | °C |
| par36 | Heizen Solltemperatur | °C |
| par37 | Warmwasser Ladetemperatur | °C |
| par38 | Warmwasser Hysterese | K |
| par50 | Betriebsstunden Kompressor | h |
| par51 | Betriebsstunden Heizen | h |
| par52 | Betriebsstunden Warmwasser | h |
| par53 | Starts Kompressor | – |

Unbekannte Parameter werden automatisch als `Parameter parXX` angelegt.  
Bitte ein Issue eröffnen, wenn du weitere Parameter kennst!

### 🔧 Erweiterte Konfiguration (für Entwickler)

Abweichende Endpunkte lassen sich in `const.py` anpassen:

```python
LOGIN_PATH  = "/index.php"         # relativer Pfad zum Login
DATA_PATH   = "/index.php"         # relativer Pfad zu den Daten
DATA_PARAMS = {"s": "realdata"}    # Query-Parameter für den Datenabruf
```

### 🐛 Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| „Anmeldung fehlgeschlagen" | Zugangsdaten im Portal prüfen |
| Keine Sensordaten | HA-Logs prüfen; `DATA_PATH` / `DATA_PARAMS` ggf. anpassen |
| Dashboard fehlt | HA einmal neu starten |
| Sensoren `unavailable` | Netzwerkverbindung und Portal-Erreichbarkeit prüfen |
| Unbekannte Parameter | Issue mit Parameterbezeichnung und Wert öffnen |

---

<a name="english"></a>
## 🇬🇧 English

Home Assistant integration for **Energy Save heat pumps** via the [myheatpump.com](https://www.myheatpump.com) portal.  
Automatic login, session management, sensor creation, and **fully automatic dashboard installation** – no manual YAML configuration required.

### ✨ Features

| Feature | Description |
|---------|-------------|
| 🔐 Automatic Login | Enter credentials once – the integration handles everything else |
| 🔄 Session Management | Automatic session renewal without restarts |
| 📊 All Sensors | 34+ known parameters with friendly names, units, and device classes |
| 🔍 Unknown Parameters | New parameters are created as `Parameter parXX` – no data is lost |
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

- **Temperatures** – Outdoor, flow, return, hot water (actual/setpoint)
- **Temperature history (24h)** – History graph
- **Operation & Power** – Operating mode, compressor, fan, pumps, COP
- **Refrigerant circuit** – Suction gas, hot gas, high/low pressure
- **Total energy** – Heat and electricity for heating and hot water
- **Heating curve & settings** – Slope, parallel shift, setpoints
- **Operating hours** – Compressor, heating, hot water, starts
- **Energy balance view** – Bar charts (14 days)

### 🌡️ Known Sensors

| Parameter | Name | Unit |
|-----------|------|------|
| par1 | Outdoor temperature | °C |
| par2 | Flow temperature | °C |
| par3 | Return temperature | °C |
| par4 | Hot water actual | °C |
| par5 | Hot water setpoint | °C |
| par6 | Flow setpoint | °C |
| par7 | Suction gas temperature | °C |
| par8 | Hot gas temperature | °C |
| par9 | Condensation temperature | °C |
| par10 | Evaporation temperature | °C |
| par11 | Refrigerant high pressure | bar |
| par12 | Refrigerant low pressure | bar |
| par13 | Power consumption | kW |
| par14 | Heating power | kW |
| par15 | COP (coefficient of performance) | – |
| par16 | Total energy heating | kWh |
| par17 | Total energy hot water | kWh |
| par18 | Total electricity heating | kWh |
| par19 | Total electricity hot water | kWh |
| par20 | Operating mode | – |
| par21 | Compressor frequency | Hz |
| par22 | Fan speed | rpm |
| par23 | Heating circuit pump | % |
| par24 | Hot water pump | % |
| par30 | Heating curve slope | – |
| par31 | Heating curve parallel shift | K |
| par35 | Heating switch-on temperature | °C |
| par36 | Heating setpoint temperature | °C |
| par37 | Hot water loading temperature | °C |
| par38 | Hot water hysteresis | K |
| par50 | Compressor operating hours | h |
| par51 | Heating operating hours | h |
| par52 | Hot water operating hours | h |
| par53 | Compressor starts | – |

Unknown parameters are automatically added as `Parameter parXX`.  
Please open an issue if you identify additional parameters!

### 🔧 Advanced Configuration (for developers)

If your installation uses a different endpoint, adjust `const.py`:

```python
LOGIN_PATH  = "/index.php"         # relative path to the login endpoint
DATA_PATH   = "/index.php"         # relative path to the data endpoint
DATA_PARAMS = {"s": "realdata"}    # query parameters for the data request
```

The `_normalize()` method in `coordinator.py` automatically handles multiple known JSON response shapes.

### 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Login failed" | Check credentials on the myheatpump.com portal |
| No sensor data | Check HA logs; adjust `DATA_PATH` / `DATA_PARAMS` if needed |
| Dashboard missing | Restart HA once |
| Sensors `unavailable` | Check network connectivity and portal availability |
| Unknown parameters | Open an issue with the parameter name and value |

---

## 📁 Repository Structure

```
ha-es-heatpump/
├── hacs.json
├── README.md
├── custom_components/es_heatpump/
│   ├── __init__.py              # Integration setup & teardown + dashboard trigger
│   ├── manifest.json            # HA integration manifest
│   ├── const.py                 # Parameter mapping (34 known sensors)
│   ├── coordinator.py           # Login + session management + polling
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

## 📄 License

MIT – Contributions welcome! 🎉  
If this integration saves you time, a ⭐ on GitHub is appreciated!
