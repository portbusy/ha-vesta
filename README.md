# 🏛️ Vesta

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/portbusy/ha-vesta?style=for-the-badge)](https://github.com/portbusy/ha-vesta/releases)
[![License](https://img.shields.io/github/license/portbusy/ha-vesta?style=for-the-badge)](LICENSE)
![Maintainer](https://img.shields.io/badge/maintainer-%40davidebertolotti-blue?style=for-the-badge)

**Vesta** is an advanced, predictive, and learning climate controller for Home Assistant, designed to replicate and improve upon the **Tado** experience.

## ✨ Key Features

- **🧠 Thermal Learning**: Automatically learns how fast each room heats up and cools down to optimize heating cycles.
- **🚗 Predictive Pre-heating**: Calculates arrival time based on your distance and speed, starting the heat exactly when needed.
- **🏠 Global & Local Control**: Define home-wide settings (Vacation, Away temps) with the ability to override them per room.
- **🛡️ Robust Safety Guards**: 
  - **Frost Protection**: Forces heating if temp drops below 5°C, even if windows are open.
  - **Hardware Failure Detection**: Alerts you if a valve is stuck or the boiler fails.
  - **Manual Timeout**: Automatically reverts to schedule after 4 hours of manual override.
- **🏘️ Room-Centric Design**: Group multiple TRVs in a single room controlled by one high-precision master sensor.
- **❄️ Window Detection**: Pauses heating when windows are open (with frost override).

## 🚀 Installation

### Option 1: HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add `https://github.com/portbusy/ha-vesta` with category **Integration**.
4. Click **Install**.
5. Restart Home Assistant.

### Option 2: Manual
1. Copy the `custom_components/vesta` folder into your Home Assistant's `custom_components` directory.
2. Restart Home Assistant.

## ⚙️ Configuration

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Vesta**.
3. First, run the **Global Home Settings** to set your family's defaults.
4. Then, add each **Room** individually.

## 🛠️ How it Works

Vesta uses a sophisticated decision engine that combines:
- **PID Control**: Precise power calculation (0-100%).
- **PWM Modulation**: Controls standard on/off valves with high-precision pulses.
- **Weather Compensation**: Adjusts targets based on outdoor temperature.
- **Geofencing Hysteresis**: Prevents rapid switching near the home boundary.

---
Developed with ❤️ by [@davidebertolotti](https://github.com/davidebertolotti)
