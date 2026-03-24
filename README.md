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

1. **Frost protection** — If the room drops below 5°C, heating is forced on regardless of schedule, mode, or open windows. This cannot be disabled.
2. **Vacation mode** — All rooms hold at anti-frost temperature (5°C). Activatable globally or per-room.
3. **Away mode** — When everyone is away, rooms drop to a lower "away" temperature to save energy.
4. **Pre-heating on return** — When you're heading home, Vesta calculates how long it takes to heat the room vs. how long until you arrive, and starts heating early so the room is ready when you walk in.
5. **Schedule** — When you're home, a Home Assistant schedule helper controls when comfort temperature applies and when the room should be at a lower eco temperature.
6. **Manual override** — You can set any temperature directly. Vesta holds it for 4 hours, then returns to the schedule automatically.

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
- **Area auto-discovery** — When adding a room, select a Home Assistant area and Vesta automatically finds the heaters, temperature sensor, and window sensor assigned to it.

---

## Schedule block additional data

Each block in a Schedule helper can carry a JSON payload in the "Additional data" field. Vesta reads this to determine the target temperature for that block:

| Data | Effect |
|------|--------|
| `{"temp": 22.5}` | Hold exactly 22.5°C |
| `{"mode": "comfort"}` | Use the configured comfort temperature |
| `{"mode": "eco"}` | Use the eco temperature |
| `{"mode": "away"}` | Use the away temperature |
| `{"mode": "frost"}` | Hold at 5°C (anti-frost only) |
| `{"mode": "off"}` | Turn off heating for this block |
| *(empty or absent)* | ON block → comfort temp, OFF block → eco temp |

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
3. The first time, configure **Global Home Settings** — comfort, eco, and away temperatures, your presence sensors, schedule, and weather entity.
4. Then add each **Room** individually. Select the area to auto-discover entities, or configure them manually.

Global settings apply to all rooms by default. When editing a room, you can override any setting (schedule, presence sensors, comfort temperature, away temperature) specifically for that room.

---

Developed with ❤️ by [@portbusy](https://github.com/portbusy)
