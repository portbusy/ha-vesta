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
CONF_VACATION_ENTITY = "vacation_entity"
CONF_HEATING_SEASON_ENTITY = "heating_season_entity"
CONF_HEATING_SEASON_ACTIVE = "heating_season_active"
CONF_HEATING_SEASON_OFFMODE = "heating_season_offmode"
CONF_BOILER_ENTITY = "boiler_entity"
CONF_BOILER_OFFSET = "boiler_offset"
CONF_WINDOW_DELAY = "window_delay"
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

# Manual override behaviour
CONF_MANUAL_OVERRIDE_MODE = "manual_override_mode"
CONF_MANUAL_OVERRIDE_HOURS = "manual_override_hours"

MANUAL_OVERRIDE_TIMER = "timer"
MANUAL_OVERRIDE_NEXT_SCHEDULE = "next_schedule"
MANUAL_OVERRIDE_NEXT_SCHEDULE_ON = "next_schedule_on"
MANUAL_OVERRIDE_ON_ARRIVAL = "on_arrival"
MANUAL_OVERRIDE_ON_DEPARTURE = "on_departure"
MANUAL_OVERRIDE_PERMANENT = "permanent"
MANUAL_OVERRIDE_TIMER_OR_SCHEDULE = "timer_or_schedule"

# Override Toggles (per Room)
CONF_OVERRIDE_COMFORT = "override_comfort"
CONF_OVERRIDE_ECO = "override_eco"
CONF_OVERRIDE_AWAY = "override_away"
CONF_OVERRIDE_PRESENCE = "override_presence"
CONF_OVERRIDE_WEATHER = "override_weather"
CONF_OVERRIDE_SCHEDULE = "override_schedule"
CONF_OVERRIDE_MANUAL_MODE = "override_manual_mode"

# Attributes
ATTR_HEATING_RATE = "heating_rate_deg_min"
ATTR_COOLING_RATE = "cooling_rate_deg_min"
ATTR_HEATING_POWER = "heating_power"
ATTR_DAILY_USAGE = "daily_usage_minutes"
ATTR_NEAREST_DISTANCE = "nearest_distance"
ATTR_VACATION_MODE = "vacation_mode_active"
ATTR_HEATING_SEASON = "heating_season_active"

# Heating season off-mode options
SEASON_OFFMODE_OPEN = "open"
SEASON_OFFMODE_FROST = "frost"
SEASON_OFFMODE_OFF = "off"
ATTR_EMERGENCY_HEAT = "emergency_heat_active"
ATTR_OUTDOOR_TEMP = "outdoor_temperature"

# Energy / Savings
CONF_ENERGY_PRICE_KWH = "energy_price_kwh"
CONF_ENERGY_ANNUAL_DATA = "energy_annual_data"   # {year_str: kwh_float}
CONF_ENERGY_KWH_THIS_YEAR = "energy_kwh_this_year"  # UI-only, merged into annual_data

ATTR_SAVED_AWAY_H_TODAY = "saved_away_hours_today"
ATTR_SAVED_WINDOW_H_TODAY = "saved_window_hours_today"
ATTR_SAVED_ECO_H_TODAY = "saved_eco_hours_today"
ATTR_SAVED_AWAY_H_MONTH = "saved_away_hours_month"
ATTR_SAVED_WINDOW_H_MONTH = "saved_window_hours_month"
ATTR_SAVED_ECO_H_MONTH = "saved_eco_hours_month"
ATTR_ACTUAL_HEATING_H_MONTH = "actual_heating_hours_month"
ATTR_SAVINGS_KWH_MONTH = "estimated_savings_kwh_month"
ATTR_SAVINGS_EUR_MONTH = "estimated_savings_eur_month"

DEFAULT_NAME = "Smart Climate Control"

# Modes
MODE_SMART_SCHEDULE = "smart_schedule"
MODE_MANUAL = "manual"
MODE_AWAY = "away"
MODE_VACATION = "vacation"