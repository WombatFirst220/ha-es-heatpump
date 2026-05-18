"""Constants for the ES Heatpump integration."""

DOMAIN = "es_heatpump"
PLATFORMS = ["sensor"]

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_BASE_URL       = "base_url"
CONF_SCAN_INTERVAL  = "scan_interval"
CONF_POWER_ENTITY   = "power_entity"
CONF_FLOW_RATE      = "flow_rate"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL      = "https://www.myheatpump.com"
DEFAULT_SCAN_INTERVAL = 60          # seconds
DEFAULT_FLOW_RATE     = 1.2         # m³/h — typical for AW12-R32 at full load

# Known myheatpump.com regional portals.  Users can still type any custom URL.
KNOWN_BASE_URLS = [
    "https://www.myheatpump.com",   # global / China
    "https://eu.myheatpump.com",    # EU server
]

# ── API endpoints (verified March 2026 against live portal) ──────────────────
LOGIN_PATH          = "/a/login"
DEVICE_LIST_PATH    = "/a/amt/deviceList/listData"
REALDATA_PATH       = "/a/amt/realdata/get"
SESSION_COOKIE_NAME = "JSESSIONID"

# ── Calculated sensor identifiers (not from API) ─────────────────────────────
CALC_SPREIZUNG      = "calc_spreizung"
CALC_THERM_LEISTUNG = "calc_therm_leistung"
CALC_COP            = "calc_cop"
CALC_ELEC_POWER     = "calc_elec_power"   # mirror of the configured power_entity

# ── Betriebsart enum mapping (par15) ─────────────────────────────────────────
# Confirmed via portal field "Unit Current Working Mode" + user observation.
# Numeric values from the API are mapped to display strings; unknown values
# fall back to "Unbekannt".
BETRIEBSART_VALUES = {
    0.0: "Aus",
    1.0: "Brauchwasser",
    2.0: "Heizen",
    3.0: "Entfrosten",
}
BETRIEBSART_OPTIONS = ["Aus", "Brauchwasser", "Heizen", "Entfrosten", "Unbekannt"]

# ── Device info ──────────────────────────────────────────────────────────────
DEVICE_NAME         = "ES Wärmepumpe"
DEVICE_MANUFACTURER = "Energy Save"
DEVICE_MODEL        = "myheatpump.com"

# ── Physical constants ───────────────────────────────────────────────────────
# Wh per m³ per Kelvin (volumetric heat capacity of water at heating temps)
WATER_VOL_HEAT_CAPACITY_WH = 1163.0   # Wh/(m³·K)

# Sentinel returned by the portal for disconnected temperature sensors
TEMP_SENTINEL = -99.0


# ── Parameter → Sensor mapping ───────────────────────────────────────────────
# VERIFIED 2026-05-18 via Pearson correlation of plugin parXX vs. the user's
# multiscrape sensors (es_wp_*) during a live heating cycle 18:00-18:30.
#
# Fields:
#   slug             : suffix for entity_id → sensor.es_hp_<slug>
#   name             : friendly display name
#   unit             : native_unit_of_measurement
#   device_class     : SensorDeviceClass string
#   state_class      : SensorStateClass string
#   icon             : Material Design icon
#   enabled_default  : True = visible by default
#                      False = registered but disabled (user can enable in UI)
#
# All listed parameters have been positively identified or have a defined
# diagnostic role. Parameters NOT in this dict are NOT created as entities.
#
PARAMETER_SENSORS = {
    # ── Temperatures (high-confidence verified) ──────────────────────────
    "par4": {
        "slug": "vorlauf_tuo",
        "name": "Vorlauftemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-up",
        "enabled_default": True,
    },
    "par5": {
        "slug": "ruecklauf_tui",
        "name": "Rücklauftemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-down",
        "enabled_default": True,
    },
    "par6": {
        "slug": "heizen_soll",
        "name": "Heizen Solltemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-check",
        "enabled_default": True,
    },
    "par7": {
        "slug": "warmwasser_tw",
        "name": "Warmwasser",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:water-thermometer",
        "enabled_default": True,
    },
    "par8": {
        "slug": "heizen",
        "name": "Heizwasser Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:radiator",
        "enabled_default": True,
    },
    "par9": {
        "slug": "mischventil_1",
        "name": "Mischventil 1 Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:valve",
        "enabled_default": True,
    },
    "par10": {
        "slug": "mischventil_2",
        "name": "Mischventil 2 Temperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:valve",
        "enabled_default": False,  # often -99 (not connected)
    },
    "par11": {
        "slug": "raumtemperatur",
        "name": "Raumtemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:home-thermometer",
        "enabled_default": True,
    },
    "par24": {
        "slug": "aussentemp_ta",
        "name": "Außentemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
        "enabled_default": True,
    },
    "par25": {
        # ⚡ Verified 2026-05-18: r=+0.998 with es_wp_heissgas_td, MAD=0.35 °C
        "slug": "heissgas_td",
        "name": "Heißgastemperatur",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:fire",
        "enabled_default": True,
    },

    "par36": {
        # ⚡ Reported in GitHub issue #1 (ohlavin, 2026-04-08):
        # "Set temp. for Heating (without heating curve)" — Heating/Cooling
        # Circuit 1 setpoint from the portal settings page.
        "slug": "heizen_soll_manuell",
        "name": "Heizen Solltemperatur (manuell)",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer-plus",
        "enabled_default": True,
    },

    # ── Compressor / Operation ───────────────────────────────────────────
    "par15": {
        # Text-mapped via BETRIEBSART_VALUES at runtime (see sensor.py)
        "slug": "betriebsart",
        "name": "Betriebsart",
        "unit": None,
        "device_class": "enum",
        "state_class": None,
        "options": BETRIEBSART_OPTIONS,
        "value_map": BETRIEBSART_VALUES,
        "icon": "mdi:heat-pump",
        "enabled_default": True,
    },
    "par20": {
        "slug": "frequenz_hz",
        "name": "Kompressor Frequenz",
        "unit": "Hz", "device_class": "frequency", "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "enabled_default": True,
    },

    # ── Electrical ───────────────────────────────────────────────────────
    "par31": {
        "slug": "spannung",
        "name": "Spannung",
        "unit": "V", "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:lightning-bolt",
        "enabled_default": True,
    },

    # ── Device info / counters ───────────────────────────────────────────
    "par37": {
        "slug": "software_version",
        "name": "Software Version",
        "unit": None, "device_class": None, "state_class": None,
        "icon": "mdi:chip",
        "enabled_default": False,   # diagnostic
    },
    "par41": {
        "slug": "ah_betriebszeit",
        "name": "AH Betriebszeit",
        "unit": "min", "device_class": "duration", "state_class": "total_increasing",
        "icon": "mdi:timer-outline",
        "enabled_default": True,
    },
    "par42": {
        "slug": "hbh_betriebszeit",
        "name": "HBH Betriebszeit",
        "unit": "min", "device_class": "duration", "state_class": "total_increasing",
        "icon": "mdi:timer",
        "enabled_default": True,
    },
    "par43": {
        "slug": "hwtbh_betriebszeit",
        "name": "HWTBH Betriebszeit",
        "unit": "min", "device_class": "duration", "state_class": "total_increasing",
        "icon": "mdi:timer",
        "enabled_default": False,   # usually 0
    },

    # ── Diagnostic / not eindeutig identifiziert (disabled by default) ───
    # These correlate with operating state but couldn't be mapped to a
    # canonical multiscrape label. They're kept as opt-in diagnostics for
    # future investigation.
    "par21": {
        "slug": "diag_par21",
        "name": "Diagnose par21 (vermutl. Kompressor Sollwert)",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:gauge",
        "enabled_default": False,
    },
    "par22": {
        "slug": "diag_par22",
        "name": "Diagnose par22 (vermutl. Kondensation Tc)",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
        "enabled_default": False,
    },
    "par23": {
        "slug": "diag_par23",
        "name": "Diagnose par23 (vermutl. Sauggas Ts)",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
        "enabled_default": False,
    },
    "par26": {
        "slug": "diag_par26",
        "name": "Diagnose par26 (vermutl. Niederdruck-Sättigung)",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
        "enabled_default": False,
    },
    "par27": {
        "slug": "diag_par27",
        "name": "Diagnose par27 (vermutl. Verdampfung Te)",
        "unit": "°C", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:thermometer",
        "enabled_default": False,
    },
    "par39": {
        "slug": "diag_par39",
        "name": "Diagnose par39",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:gauge",
        "enabled_default": False,
    },
    "par40": {
        "slug": "diag_par40",
        "name": "Diagnose par40 (vermutl. Überhitzung)",
        "unit": "K", "device_class": "temperature", "state_class": "measurement",
        "icon": "mdi:delta",
        "enabled_default": False,
    },
}
