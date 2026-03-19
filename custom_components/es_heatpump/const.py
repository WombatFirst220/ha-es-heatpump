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
# Login  : POST /a/login
#          username + password are Base64-encoded in the form payload
#          Extra fields validCode, loginValidCode, __url must be present but empty
#          Server sets JSESSIONID + heatpump.session.id cookies on success
#
# Data   : POST /a/amt/desktop/load
#          Payload : ctrlPermi=1  (form data)
#          Response: application/json  containing nested parXX sensor values
#
LOGIN_PATH        = "/a/login"
DATA_PATH         = "/a/amt/desktop/load"
DATA_PAYLOAD      = {"ctrlPermi": "1"}
SESSION_COOKIE_NAME = "JSESSIONID"

# Known parameter → sensor mapping for Energy Save / myheatpump.com
# Keys are the parameter IDs returned by the API (e.g. "par1", "par36")
# Extend this list as new parameters are discovered.
PARAMETER_SENSORS = {
    # Temperatures
    "par1":  {"name": "Außentemperatur",               "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer"},
    "par2":  {"name": "Vorlauftemperatur",              "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-chevron-up"},
    "par3":  {"name": "Rücklauftemperatur",             "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-chevron-down"},
    "par4":  {"name": "Warmwasser Ist",                 "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:water-thermometer"},
    "par5":  {"name": "Warmwasser Soll",                "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:water-thermometer-outline"},
    "par6":  {"name": "Vorlauf Soll",                   "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-lines"},
    "par7":  {"name": "Sauggastemperatur",              "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer"},
    "par8":  {"name": "Heißgastemperatur",              "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-high"},
    "par9":  {"name": "Kondensationstemperatur",        "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer"},
    "par10": {"name": "Verdampfungstemperatur",         "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-low"},
    "par11": {"name": "Kältemittel Hochdruck",         "unit": "bar", "device_class": "pressure",       "state_class": "measurement", "icon": "mdi:gauge-high"},
    "par12": {"name": "Kältemittel Niederdruck",       "unit": "bar", "device_class": "pressure",       "state_class": "measurement", "icon": "mdi:gauge-low"},
    # Power & Energy
    "par13": {"name": "Leistungsaufnahme",              "unit": "kW",  "device_class": "power",          "state_class": "measurement", "icon": "mdi:lightning-bolt"},
    "par14": {"name": "Heizleistung",                   "unit": "kW",  "device_class": "power",          "state_class": "measurement", "icon": "mdi:heat-wave"},
    "par15": {"name": "COP",                            "unit": None,  "device_class": None,             "state_class": "measurement", "icon": "mdi:chart-line"},
    "par16": {"name": "Energie Heizen gesamt",          "unit": "kWh", "device_class": "energy",         "state_class": "total_increasing", "icon": "mdi:counter"},
    "par17": {"name": "Energie Warmwasser gesamt",      "unit": "kWh", "device_class": "energy",         "state_class": "total_increasing", "icon": "mdi:counter"},
    "par18": {"name": "Strom Heizen gesamt",            "unit": "kWh", "device_class": "energy",         "state_class": "total_increasing", "icon": "mdi:counter"},
    "par19": {"name": "Strom Warmwasser gesamt",        "unit": "kWh", "device_class": "energy",         "state_class": "total_increasing", "icon": "mdi:counter"},
    # Operating state
    "par20": {"name": "Betriebsmodus",                  "unit": None,  "device_class": None,             "state_class": None,           "icon": "mdi:heat-pump"},
    "par21": {"name": "Kompressor Frequenz",            "unit": "Hz",  "device_class": "frequency",      "state_class": "measurement", "icon": "mdi:sine-wave"},
    "par22": {"name": "Lüfter Drehzahl",               "unit": "rpm", "device_class": None,             "state_class": "measurement", "icon": "mdi:fan"},
    "par23": {"name": "Pumpe Heizkreis",                "unit": "%",   "device_class": None,             "state_class": "measurement", "icon": "mdi:pump"},
    "par24": {"name": "Pumpe Warmwasser",               "unit": "%",   "device_class": None,             "state_class": "measurement", "icon": "mdi:pump"},
    # Setpoints / control
    "par30": {"name": "Heizkurve Steilheit",            "unit": None,  "device_class": None,             "state_class": "measurement", "icon": "mdi:chart-bell-curve"},
    "par31": {"name": "Heizkurve Parallelverschiebung", "unit": "K",   "device_class": None,             "state_class": "measurement", "icon": "mdi:arrow-up-down"},
    "par35": {"name": "Heizen Einschalttemperatur",     "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-plus"},
    "par36": {"name": "Heizen Solltemperatur",          "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:thermometer-check"},
    "par37": {"name": "Warmwasser Ladetemperatur",      "unit": "°C",  "device_class": "temperature",    "state_class": "measurement", "icon": "mdi:water-boiler"},
    "par38": {"name": "Warmwasser Hystere",             "unit": "K",   "device_class": None,             "state_class": "measurement", "icon": "mdi:delta"},
    # Runtime counters
    "par50": {"name": "Betriebsstunden Kompressor",     "unit": "h",   "device_class": None,             "state_class": "total_increasing", "icon": "mdi:timer-outline"},
    "par51": {"name": "Betriebsstunden Heizen",         "unit": "h",   "device_class": None,             "state_class": "total_increasing", "icon": "mdi:timer"},
    "par52": {"name": "Betriebsstunden Warmwasser",     "unit": "h",   "device_class": None,             "state_class": "total_increasing", "icon": "mdi:timer"},
    "par53": {"name": "Starts Kompressor",              "unit": None,  "device_class": None,             "state_class": "total_increasing", "icon": "mdi:counter"},
}

# Device info
DEVICE_NAME = "ES Wärmepumpe"
DEVICE_MANUFACTURER = "Energy Save"
DEVICE_MODEL = "myheatpump.com"
