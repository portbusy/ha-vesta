"""Constants for Vesta with Full Global/Local logic."""

DOMAIN = "vesta"
CONF_HEATER_ENTITIES = "heaters"
CONF_SENSOR = "target_sensor"
CONF_WINDOW_SENSOR = "window_sensor"
CONF_PRESENCE_SENSORS = "presence_sensors"
CONF_SCHEDULE = "schedule_entity"
CONF_WEATHER = "weather_entity"
CONF_OVERRIDE_SWITCH = "override_switch"
CONF_VACATION_STATE = "vacation_state"
CONF_NAME = "name"
CONF_AREA = "area"

# Config Type
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_GLOBAL = "global"
ENTRY_TYPE_ROOM = "room"

# Settings & Overrides
CONF_COMFORT_TEMP = "comfort_temp"
CONF_ECO_TEMP = "eco_temp"
CONF_AWAY_TEMP = "away_temp"
CONF_AVG_SPEED = "avg_travel_speed"

# Override Toggles (per Room)
CONF_OVERRIDE_COMFORT = "override_comfort"
CONF_OVERRIDE_AWAY = "override_away"
CONF_OVERRIDE_SPEED = "override_speed"
CONF_OVERRIDE_PRESENCE = "override_presence"
CONF_OVERRIDE_WEATHER = "override_weather"
CONF_OVERRIDE_SCHEDULE = "override_schedule"

# Attributes
ATTR_HEATING_RATE = "heating_rate_deg_min"
ATTR_COOLING_RATE = "cooling_rate_deg_min"
ATTR_HEATING_POWER = "heating_power"
ATTR_DAILY_USAGE = "daily_usage_minutes"
ATTR_NEAREST_DISTANCE = "nearest_distance"
ATTR_VACATION_MODE = "vacation_mode_active"
ATTR_OUTDOOR_TEMP = "outdoor_temperature"

DEFAULT_NAME = "Smart Climate Control"

# Modes
MODE_SMART_SCHEDULE = "smart_schedule"
MODE_MANUAL = "manual"
MODE_AWAY = "away"
MODE_VACATION = "vacation"