"""Constants for the ES Heatpump integration."""

DOMAIN = "es_heatpump"
PLATFORMS = ["sensor"]

# Config entry keys
CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_BASE_URL = "https://www.myheatpump.com"
DEFAULT_SCAN_INTERVAL = 60  # seconds

# ── Verified API endpoints (myheatpump.com, March 2026) ─────────────────────
#
# Step 1 – Login
#   POST /a/login
#   Payload : username=<Base64>, password=<Base64>,
#             validCode=, loginValidCode=, __url=
#   Response: {"msg": "Login successful!"} + sets JSESSIONID cookie
#
# Step 2 – Device list  (fetched once after login to get mn + devid)
#   POST /a/amt/deviceList/listData
#   Payload : (empty)
#   Response: list/dict containing device entries with "mn" and "devid" fields
#
# Step 3 – Sensor data  (fetched every poll interval)
#   POST /a/amt/realdata/get
#   Payload : mn=<device mn>, devid=<device devid>
#   Response: flat JSON  {"par1": 2.0, "par2": 0.0, ..., "mn": ..., "devid": ...}
#
LOGIN_PATH          = "/a/login"
DEVICE_LIST_PATH    = "/a/amt/deviceList/listData"
REALDATA_PATH       = "/a/amt/realdata/get"
SESSION_COOKIE_NAME = "JSESSIONID"

# ── Parameter → Sensor mapping ───────────────────────────────────────────────
# Verified by cross-referencing live myheatpump.com portal UI values with the
# raw par values returned by /a/amt/realdata/get  (March 2026, Valtop AW12-R32)
#
# Confidence legend:
#   ✓  = confirmed via exact or near-exact live value match
#   ~  = plausible but not yet confirmed (value was 0.0 or ambiguous)
#   ?  = unknown / needs further investigation
#
PARAMETER_SENSORS = {
    # ── Temperatures (verified) ───────────────────────────────────────────
    "par6":  {  # Set Temperature = 32  →  par6 = 32.1  ✓
        "name": "Heizen Solltemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-check",
    },
    "par7":  {  # Sanitary Hot Water Temp TW = 50.3  →  par7 = 50.5  ✓
        "name": "Warmwasser Ist",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:water-thermometer",
    },
    "par8":  {  # Cooling/Heating Water Temp TC = 34.6  →  par8 = 34.3  ✓
        "name": "Heizkreis Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-up",
    },
    "par9":  {  # Water Temp After Mixing Valve 1 = 23.4  →  par9 = 23.6  ✓
        "name": "Mischventil 1 Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:valve",
    },
    "par10": {  # Water Temp After Mixing Valve 2 = -99  →  par10 = -99.0  ✓
        "name": "Mischventil 2 Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:valve",
    },
    "par11": {  # Room Temp TR = 21.5  →  par11 = 21.9  ✓
        "name": "Raumtemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:home-thermometer",
    },
    "par24": {  # Actual Ambient Temp Ta = 4.8  →  par24 = 4.8  ✓
        "name": "Außentemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    # ── Temperatures (unconfirmed – value was not visible in current screenshot) ~
    "par4":  {  # ~ Vorlauftemperatur (par4 = 35.1, plausible for flow temp)
        "name": "Vorlauftemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-up",
    },
    "par5":  {  # ~ Rücklauftemperatur (par5 = 33.6, plausible for return temp)
        "name": "Rücklauftemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-down",
    },
    "par22": {  # ~ Temperatur (par22 = 21.8, near room temp – purpose unclear)
        "name": "Temperatur par22",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    "par25": {  # ~ Temperatur (par25 = 37.7 – purpose unclear)
        "name": "Temperatur par25",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    "par30": {  # ~ Temperatur (par30 = 4.8, same as Außentemp – possibly duplicate or sensor 2)
        "name": "Temperatur par30",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    # ── Compressor & fan ─────────────────────────────────────────────────
    "par20": {  # Comp. Speed Hz = 43  →  par20 = 43.0  ✓
        "name": "Kompressor Frequenz",
        "unit": "Hz", "device_class": "frequency", "state_class": "measurement",
        "icon": "mdi:sine-wave",
    },
    "par38": {  # Calculated Comp. Speed = 2  →  par38 = 2.0  ✓
        "name": "Kompressor Drehzahl berechnet",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:rotate-right",
    },
    "par21": {  # ~ par21 = 400.0 – likely fan speed RPM
        "name": "Lüfter Drehzahl",
        "unit": "rpm", "device_class": None, "state_class": "measurement",
        "icon": "mdi:fan",
    },
    # ── Electrical ───────────────────────────────────────────────────────
    "par31": {  # Voltage = 231 V  →  par31 = 231.0  ✓
        "name": "Spannung",
        "unit": "V", "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:lightning-bolt",
    },
    "par26": {  # ~ par26 = 1.8 – possibly current (A) or power (kW)
        "name": "Leistungsaufnahme",
        "unit": "kW", "device_class": "power", "state_class": "measurement",
        "icon": "mdi:lightning-bolt",
    },
    "par28": {  # ~ par28 = 560.0 – possibly total energy counter (Wh or kWh?)
        "name": "Energie gesamt",
        "unit": "kWh", "device_class": "energy", "state_class": "total_increasing",
        "icon": "mdi:counter",
    },
    # ── Operating mode ───────────────────────────────────────────────────
    "par15": {  # Unit Current Working Mode: Heating  →  par15 = 1.0  ✓ (1=Heating)
        "name": "Betriebsmodus",
        "unit": None, "device_class": None, "state_class": None,
        "icon": "mdi:heat-pump",
    },
    # ── Pump status ──────────────────────────────────────────────────────
    "par27": {  # ~ Pump status P0 = 1  →  par27 = 1.0  (most likely)
        "name": "Pumpe P0 Status",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
    },
    "par33": {  # ~ Pump status P1 = 1  →  par33 = 1.0  (most likely)
        "name": "Pumpe P1 Status",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
    },
    "par34": {  # ~ Pump status P2 = 0  →  par34 = 1.0  (uncertain – P2 showed 0 in portal)
        "name": "Pumpe P2 Status",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
    },
    # ── Software / device info ───────────────────────────────────────────
    "par37": {  # Software Version = 218  →  par37 = 218.0  ✓
        "name": "Software Version",
        "unit": None, "device_class": None, "state_class": None,
        "icon": "mdi:chip",
    },
    # ── Runtime counters ─────────────────────────────────────────────────
    "par41": {  # AH Working Time = 49115 min  →  par41 = 49115.0  ✓
        "name": "AH Betriebszeit",
        "unit": "min", "device_class": None, "state_class": "total_increasing",
        "icon": "mdi:timer-outline",
    },
    "par42": {  # HBH Working Time = 9564 min  →  par42 = 9564.0  ✓
        "name": "HBH Betriebszeit",
        "unit": "min", "device_class": None, "state_class": "total_increasing",
        "icon": "mdi:timer",
    },
    "par43": {  # ~ HWTBH Working Time = 0 min  →  par43 = 0.0  (most likely)
        "name": "HWTBH Betriebszeit",
        "unit": "min", "device_class": None, "state_class": "total_increasing",
        "icon": "mdi:timer",
    },
    # ── Unknown / needs investigation ────────────────────────────────────
    # par1  = 2.0   ?
    # par2  = 0.0   ?
    # par3  = 0.0   ?
    # par12 = 0.0   ?
    # par13 = 0.0   ?
    # par14 = 0.0   ?
    # par16 = 0.0   ?
    # par17 = 0.0   ?
    # par18 = 0.0   ?
    # par19 = 0.0   ?
    # par23 = 6.8   ?  (possibly pump speed %)
    # par29 = 0.0   ?
    # par32 = 0.0   ?
    # par35 = 0.0   ?
    # par36 = 33.0  ?  (close to set temp 32 – maybe Warmwasser Soll?)
    # par39 = 2.7   ?
    # par40 = 0.3   ?
    # par44..par48  = 0.0  ?
}

# Device info
DEVICE_NAME         = "ES Wärmepumpe"
DEVICE_MANUFACTURER = "Energy Save"
DEVICE_MODEL        = "myheatpump.com"
