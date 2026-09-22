"""Constants for the ES Heatpump integration."""

DOMAIN = "es_heatpump"
PLATFORMS = ["sensor"]

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_BASE_URL         = "base_url"
CONF_SCAN_INTERVAL    = "scan_interval"
CONF_POWER_ENTITY     = "power_entity"
CONF_FLOW_RATE        = "flow_rate"           # Heizen (heating circuit)
CONF_FLOW_RATE_DHW    = "flow_rate_dhw"       # Brauchwasser (DHW circuit)
CONF_MODE_SOURCE      = "mode_source_entity"  # optional external override for the mode
CONF_DHW_MARGIN_K     = "dhw_margin_k"        # Vorlauf-über-Soll threshold for DHW detection
CONF_FLOW_ENTITY      = "flow_entity"         # optional live volumetric-flow sensor
CONF_MODEL            = "model"               # picks the datasheet nominal flow rate

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL        = "https://www.myheatpump.com"
DEFAULT_SCAN_INTERVAL   = 60        # seconds
DEFAULT_FLOW_RATE       = 1.2       # m³/h — see NOMINAL_FLOW_RATES_M3H, set per model!
DEFAULT_FLOW_RATE_DHW   = 1.0       # m³/h — DHW coil circuit, typical default
DEFAULT_DHW_MARGIN_K    = 8.0       # K — Vorlauf above heating setpoint ⇒ DHW mode

# Nominal water flow per model, from the ES datasheet
# "ES V8 Luft/Wasser Wärmepumpen AWC-R32-M, Monoblock Serie", row
# "Zulässiger Wasserdurchfluss Min / Nominal" (l/s), converted to m³/h.
#
#   Setting flow_rate too low is the single most common configuration error:
#   the thermal power and COP are CALCULATED from it, so a wrong value makes
#   both meaningless.  A COP below 1 is physically impossible and always means
#   the flow rate is too low — see the plausibility warning in sensor.py.
MODEL_UNKNOWN = "andere / unbekannt"

NOMINAL_FLOW_RATES_M3H = {
    #  model          min    nominal
    "AWC6-R32-M-V8":  (0.65, 1.01),
    "AWC9-R32-M-V8":  (0.94, 1.55),
    "AWC12-R32-M-V8": (1.44, 2.02),
    "AWC15-R32-M-V8": (2.23, 2.59),
    "AWC19-R32-M-V8": (2.66, 3.28),
}

# A modulating circulation pump (proportional-pressure or "Auto" mode) changes
# the flow with the load, so a single constant can only ever be exact at one
# operating point.  Telltale sign in the data: the spread stays roughly flat
# while the compressor power varies by a factor of two or more.  Users with a
# flow meter can wire it up via CONF_FLOW_ENTITY and skip the constant
# altogether.  Unit expected: m³/h (l/min and l/h are converted automatically).
FLOW_ENTITY_UNITS_TO_M3H = {
    "m³/h": 1.0, "m3/h": 1.0,
    "l/min": 0.06, "L/min": 0.06,
    "l/h": 0.001, "L/h": 0.001,
    "l/s": 3.6, "L/s": 3.6,
}

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
CALC_ELEC_POWER     = "calc_elec_power"     # mirror of the configured power_entity
CALC_BETRIEBSART    = "calc_betriebsart"    # derived from mode_source_entity

# ── Betriebsart: die Geraeteangabe par1 ──────────────────────────────────────
# Die Formularseite des Portals (/a/amt/realdata/form) benennt par1 als
# "Unit Current Working Mode" und liefert die Bedeutungen als <select>-Optionen
# gleich mit.  par1 steckt im normalen JSON-Endpunkt /a/amt/realdata/get - es
# wurde bis v2.3.1 nur nie zugeordnet.  Verifiziert am 22.09.2026.
#
# Die Portal-Liste kennt KEIN Entfrosten: Abtauen ist keine Betriebsart des
# Geraets, sondern ein Vorgang innerhalb des Heizbetriebs.  Er wird weiterhin
# ueber die negative Spreizung erkannt (siehe mode.py).
PAR_BETRIEBSART = "par1"

PAR1_BETRIEBSART = {
    0: "Aus",                       # Standby
    1: "Brauchwasser",              # Sanitary Hot Water
    2: "Heizen",                    # Heating
    3: "Kuehlen",                   # Cooling
    4: "Brauchwasser + Heizen",     # Sanitary Hot Water + Heating
    5: "Brauchwasser + Kuehlen",    # Sanitary Hot Water + Cooling
}

# ── Betriebsart detection ────────────────────────────────────────────────────
# Since v2.3.0 the mode is derived from the heat pump's OWN values and needs no
# external helper entity.  The rules, in order:
#
#   par20 (compressor Hz) == 0            → "Aus"
#   par4 − par5 <= DEFROST_SPREAD_K       → "Entfrosten"   (flow colder than return)
#   par4 > par6 + dhw_margin_k            → "Brauchwasser" (flow far above heating setpoint)
#   otherwise                             → "Heizen"
#
# Comparing the flow temperature against the *heating setpoint* (par6) rather
# than an absolute threshold makes this work for underfloor heating (≈33 °C)
# and radiators (≈50 °C) alike: during DHW production the machine drives the
# flow far above whatever the heating circuit is currently asking for.
# If par6 is unusable, DHW_ABSOLUTE_FALLBACK_C is used instead.
#
# A configured ``mode_source_entity`` still wins when it yields a usable value,
# so existing setups keep working unchanged.
DEFROST_SPREAD_K        = -0.5      # K — flow below return means reverse cycle
DHW_ABSOLUTE_FALLBACK_C = 45.0      # °C — used only when par6 is unavailable

# Canonical display values for the enum sensor.  par15 was assumed to be the
# mode in v2.0.0–v2.2.0 but turned out to be a periodic heartbeat signal.
BETRIEBSART_OPTIONS = [
    "Aus", "Brauchwasser", "Heizen", "Kuehlen",
    "Brauchwasser + Heizen", "Brauchwasser + Kuehlen",
    "Entfrosten", "Unbekannt",
]

# Normalisation of typical state strings coming from external mode sources.
# Lower-case key → canonical option from BETRIEBSART_OPTIONS.
BETRIEBSART_ALIASES = {
    # German
    "aus":             "Aus",
    "off":             "Aus",
    "standby":         "Aus",
    "0":               "Aus",
    "heizen":          "Heizen",
    "heating":         "Heizen",
    "brauchwasser":    "Brauchwasser",
    "warmwasser":      "Brauchwasser",
    "dhw":             "Brauchwasser",
    "hot water":       "Brauchwasser",
    "kuehlen":         "Kuehlen",
    "kühlen":          "Kuehlen",
    "cooling":         "Kuehlen",
    "entfrosten":      "Entfrosten",
    "defrost":         "Entfrosten",
    "defrosting":      "Entfrosten",
    "abtauen":         "Entfrosten",
}

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
        # ⚠ Was assumed to be "Operating Mode" in v2.0.0 – v2.2.0, but live
        # observation (2026-05-19) showed that par15 only toggles 0/1 every
        # ~10 minutes for ~1 minute, independent of the actual mode shown by
        # the portal HTML ("Heizen" / "Brauchwasser").  It looks like a
        # heartbeat / "fresh data" signal rather than the mode.  Exposed as
        # diagnostic, disabled by default; the real mode comes from the
        # external ``mode_source_entity`` configured in the options.
        "slug": "diag_par15_heartbeat",
        "name": "Diagnose par15 (Heartbeat / unklar)",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pulse",
        "enabled_default": False,
    },
    "par33": {
        # Portal-Formular: "Pump statue-P0" (sic)
        "slug": "pumpe_p0",
        "name": "Pumpe P0",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
        "enabled_default": False,
    },
    "par34": {
        "slug": "pumpe_p1",
        "name": "Pumpe P1",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
        "enabled_default": False,
    },
    "par35": {
        "slug": "pumpe_p2",
        "name": "Pumpe P2",
        "unit": None, "device_class": None, "state_class": "measurement",
        "icon": "mdi:pump",
        "enabled_default": False,
    },
    "par38": {
        # Portal-Formular: "Calculated Comp. Speed" - der Sollwert, gegen den
        # par20 (Ist-Frequenz) laeuft.
        "slug": "frequenz_soll",
        "name": "Kompressor Frequenz (Sollwert)",
        "unit": "Hz", "device_class": "frequency", "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "enabled_default": False,
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
