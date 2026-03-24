"""Sensor platform for Vesta – savings and usage tracking."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ATTR_SAVINGS_KWH_MONTH, ATTR_SAVINGS_EUR_MONTH

# (key, name, unit, device_class, icon)
_SENSOR_DEFS: list[tuple] = [
    (
        "heating_minutes_today",
        "Heating Minutes Today",
        UnitOfTime.MINUTES,
        SensorDeviceClass.DURATION,
        "mdi:fire",
    ),
    (
        "saved_away_hours_today",
        "Saved Away Hours Today",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:home-export-outline",
    ),
    (
        "saved_window_hours_today",
        "Saved Window Hours Today",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:window-open-variant",
    ),
    (
        "saved_eco_hours_today",
        "Saved Eco Hours Today",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:leaf",
    ),
    (
        "heating_hours_month",
        "Heating Hours Month",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:fire",
    ),
    (
        "saved_away_hours_month",
        "Saved Away Hours Month",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:home-export-outline",
    ),
    (
        "saved_window_hours_month",
        "Saved Window Hours Month",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:window-open-variant",
    ),
    (
        "saved_eco_hours_month",
        "Saved Eco Hours Month",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        "mdi:leaf",
    ),
    (
        "savings_kwh_month",
        "Estimated Savings kWh",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        "mdi:lightning-bolt",
    ),
    (
        "savings_eur_month",
        "Estimated Savings EUR",
        "EUR",
        None,
        "mdi:currency-eur",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vesta sensor entities for a room entry."""
    climate = hass.data[DOMAIN].get("climate_entities_by_entry", {}).get(entry.entry_id)
    if climate is None:
        return

    sensors = [
        VestaSavingsSensor(climate, key, name, unit, dc, icon)
        for key, name, unit, dc, icon in _SENSOR_DEFS
    ]
    climate._companion_sensors = sensors
    async_add_entities(sensors)


class VestaSavingsSensor(SensorEntity):
    """A companion sensor exposing savings/usage data for a Vesta room."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        climate,
        key: str,
        name: str,
        unit: str,
        device_class: str | None,
        icon: str,
    ) -> None:
        self._climate = climate
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self._climate._entry.entry_id}_{self._key}"

    @property
    def device_info(self):
        return self._climate.device_info

    @property
    def native_value(self):
        c = self._climate
        if self._key == "heating_minutes_today":
            return round(c._daily_usage_seconds / 60, 1)
        if self._key == "saved_away_hours_today":
            return round(c._daily_away_s / 3600, 2)
        if self._key == "saved_window_hours_today":
            return round(c._daily_window_s / 3600, 2)
        if self._key == "saved_eco_hours_today":
            return round(c._daily_eco_s / 3600, 2)
        if self._key == "heating_hours_month":
            return round(c._monthly_actual_heating_s / 3600, 2)
        if self._key == "saved_away_hours_month":
            return round(c._monthly_away_s / 3600, 2)
        if self._key == "saved_window_hours_month":
            return round(c._monthly_window_s / 3600, 2)
        if self._key == "saved_eco_hours_month":
            return round(c._monthly_eco_s / 3600, 2)
        if self._key == "savings_kwh_month":
            return c._savings_cache.get(ATTR_SAVINGS_KWH_MONTH)
        if self._key == "savings_eur_month":
            return c._savings_cache.get(ATTR_SAVINGS_EUR_MONTH)
        return None
