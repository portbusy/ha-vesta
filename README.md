# 🏛️ Vesta

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/portbusy/ha-vesta?style=for-the-badge)](https://github.com/portbusy/ha-vesta/releases)
[![License](https://img.shields.io/github/license/portbusy/ha-vesta?style=for-the-badge)](LICENSE)
![Maintainer](https://img.shields.io/badge/maintainer-%40portbusy-blue?style=for-the-badge)

**Vesta** is a smart, self-learning climate controller for Home Assistant. It sits on top of your existing heaters — TRVs, switches, or climate entities — and takes over the logic of deciding when to heat, how much, and at what temperature, based on your schedule, presence, weather, and how your rooms actually behave over time.

Think of it as the brains Tado and similar systems provide, but running entirely local inside your Home Assistant.

---

## How it works

Every minute, Vesta evaluates each room and decides whether to turn the heater on or off. The decision is based on a layered priority system:

1. **Emergency heat override** — When a designated switch or input_boolean is turned on, all heaters are forced to maximum output immediately, ignoring mode, schedule, and window state. Intended for emergency cold situations.
2. **Frost protection** — If the room drops below 5°C, heating is forced on regardless of schedule, mode, or open windows. This cannot be disabled.
3. **Vacation mode** — All rooms hold at anti-frost temperature (5°C). Can be activated via a static toggle in Global Settings or by linking a dynamic entity (input_boolean or binary_sensor) that you control from automations or the dashboard.
4. **Away mode** — When everyone is away, rooms hold at the away temperature regardless of the schedule. The schedule resumes automatically when someone returns.
5. **Pre-heating on return** — Vesta tracks whether you are actively approaching home (GPS distance decreasing between ticks). When you are, it calculates how long the room needs to reach comfort temperature vs. how long until you arrive, and starts heating early. Stationary presence near home (office, friend's house) does not trigger pre-heating.
6. **Schedule** — When you're home, a Home Assistant schedule helper controls when comfort temperature applies and when the room should be at a lower eco temperature.
7. **Manual override** — You can set any temperature directly. Vesta holds it for 4 hours, then returns to the schedule automatically.

### Thermal learning

Vesta continuously tracks how fast each room heats up (when the heater is running) and how fast it cools down (when it's off). These rates are used to improve the pre-heating calculation over time. The learning is conservative — it only updates when the measurements are plausible and the room isn't in vacation, away, or manual mode.

### Weather compensation

If outdoor temperature drops below 5°C, Vesta automatically raises the target temperature slightly (0.1°C per degree below 5°C). This compensates for increased heat loss without any manual adjustment.

### Hardware failure detection

If the heater has been running at full power for 45 minutes but the room temperature hasn't risen, Vesta logs a warning. This catches stuck valves, boiler failures, or severely underperforming heaters before they become a problem.

---

## Features

- **Global + per-room configuration** — Set comfort, eco, and away temperatures once for the whole home. Override any of them per room when needed.
- **Schedule integration** — Uses Home Assistant's built-in Schedule helper. Each time block can carry additional data to set a specific temperature or mode directly.
- **Presence & geofencing** — Uses Person entities. Supports multiple people; the system goes to away mode only when everyone is out, and pre-heats based on the closest person's distance.
- **Window detection** — Pauses heating when a window is open. Frost protection still activates even with the window open.
- **Area auto-discovery** — When adding a room, select a Home Assistant area and Vesta automatically finds the heaters, temperature sensors, and window sensor assigned to it — including entities that inherit the area from their device.
- **Multiple temperature sensors** — Each room can use more than one temperature sensor. Readings are averaged automatically; offline sensors are excluded. If all configured sensors go offline, Vesta falls back to the TRV's own internal sensor to keep the room controlled.
- **Native TRV / climate entity support** — For climate entities (TRVs, AC units, etc.) Vesta uses `climate.set_hvac_mode` rather than generic turn on/off, so all integrations are controlled correctly regardless of whether they implement a `turn_on` service. Vesta also reads the TRV's internal temperature sensor to estimate valve openness and improve heating power calculations.
- **Vacation mode entity** — Link any input_boolean or binary_sensor to control vacation mode dynamically from automations or the dashboard. When the entity is ON, all rooms drop to anti-frost temperature. A static fallback toggle is also available for manual use.
- **Emergency heat override** — Link a switch or input_boolean to instantly force all heaters to maximum output across every room. Useful for emergency cold situations or when you need rapid heating regardless of any other setting.
- **Energy savings tracking** — Each room exposes dedicated sensor entities for heating time and hours saved per feature (away mode, window detection, eco schedule). When energy consumption and price are configured in Global Settings, Vesta also estimates monthly kWh and cost savings.

---

## Schedule block additional data

Each block in a Schedule helper can carry data in the "Additional data" field (visible under Advanced settings when editing a block). Enter it in YAML format. Vesta reads the current block's data directly from the schedule entity's state attributes.

| Data | Effect |
|------|--------|
| `temp: 22.5` | Hold exactly 22.5°C |
| `mode: comfort` | Use the configured comfort temperature |
| `mode: eco` | Use the eco temperature |
| `mode: away` | Use the away temperature |
| `mode: frost` | Hold at 5°C (anti-frost only) |
| `mode: "off"` | Turn off heating for this block |
| *(empty or absent)* | ON block → comfort temp, OFF block → eco temp |

> **Note:** `mode: off` requires quotes (`mode: "off"`) or will be parsed as a boolean by YAML. Both are accepted.

---

## Preset modes

| Preset | Behaviour |
|--------|-----------|
| **Smart Schedule** | Follows the schedule. Temperature adjusts with presence, weather, and pre-heating. |
| **Manual** | Holds the temperature you set. Reverts to Smart Schedule after 4 hours. |
| **Away** | Holds at the away temperature. Pre-heating starts automatically when you're heading home. |
| **Vacation** | Holds at 5°C (anti-frost). Presence detection does not override this mode. |

---

## Installation

[![Open Vesta on Home Assistant Community Store (HACS).](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=portbusy&repository=ha-vesta&category=integration)

### Option 1: HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add `https://github.com/portbusy/ha-vesta` with category **Integration**.
4. Click **Install**.
5. Restart Home Assistant.

### Option 2: Manual
1. Copy the `custom_components/vesta` folder into your Home Assistant's `custom_components` directory.
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Vesta**.
3. The first time, configure **Global Home Settings** — comfort, eco, and away temperatures, your presence sensors, schedule, weather entity, and optionally a vacation mode entity and/or an emergency heat override switch.
4. Then add each **Room** individually. Select the area to auto-discover entities, or configure them manually. You can select multiple temperature sensors per room.

Global settings apply to all rooms by default. When editing a room, you can override any setting (schedule, presence sensors, comfort temperature, away temperature) specifically for that room.

**Global-only settings:**

| Setting | Description |
|---------|-------------|
| Vacation Mode Entity | An input_boolean or binary_sensor. When ON, all rooms drop to 5°C. Takes priority over the static toggle. |
| Vacation Mode (static fallback) | A simple toggle to activate vacation mode when no entity is configured. |
| Emergency Heat Override | A switch or input_boolean. When ON, all heaters are forced to maximum output immediately. |

---

## Energy savings tracking

Each room creates 10 sensor entities that can be added directly to your dashboard.

**Daily (reset at midnight):**

| Sensor | Description |
|--------|-------------|
| `Heating Minutes Today` | Minutes the heater was actually on today |
| `Saved Away Hours Today` | Hours in away mode (heater suppressed) |
| `Saved Window Hours Today` | Hours heating was suppressed due to open window |
| `Saved Eco Hours Today` | Hours in eco temperature (schedule below comfort) |

**Monthly (reset on the 1st of each month):**

| Sensor | Description |
|--------|-------------|
| `Heating Hours Month` | Total heating hours this month |
| `Saved Away Hours Month` | Total away-mode suppression hours this month |
| `Saved Window Hours Month` | Total window-suppression hours this month |
| `Saved Eco Hours Month` | Total eco hours this month |

**Optional — shown only when energy data is configured:**

| Sensor | Description |
|--------|-------------|
| `Estimated Savings kWh` | Estimated kWh saved this month |
| `Estimated Savings EUR` | Estimated cost saved this month |

To enable the kWh/€ estimate, open **Global Home Settings** and fill in:
- **Energy price (€/kWh)** — your current electricity rate
- **Annual consumption (kWh)** — your home's total annual heating consumption for the current year

Vesta uses the **Heating Degree Hours (HDH)** method to estimate savings. At every scheduled tick, it accumulates the ratio of temperature setpoint reduction to the current heating demand `(comfort - actual_setpoint) / (comfort - outdoor_temp)` — so each hour of away mode on a cold night contributes more than the same hour on a mild day. When outdoor temperature is unavailable, Vesta falls back to Fraunhofer Institute reference factors (the same methodology used by Tado). The estimate is proportional to the temperature differential saved per feature: away savings are larger when the difference between comfort and away temperature is greater relative to the outdoor temperature.

---

Developed with ❤️ by [@portbusy](https://github.com/portbusy)
