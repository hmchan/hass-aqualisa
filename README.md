# Aqualisa Smart Shower for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/hmchan/hass-aqualisa)](https://github.com/hmchan/hass-aqualisa/releases)

A Home Assistant custom integration for [Aqualisa](https://www.aqualisa.co.uk/) digital smart showers. Control your shower and receive real-time status updates via Firebase Cloud Messaging push notifications — no polling required.

## Supported Devices

Any Aqualisa smart shower that works with the official Aqualisa app, including:

- Aqualisa Quartz
- Aqualisa Q
- Aqualisa Optic Q

## Features

### Entities

| Platform | Entity | Description |
|----------|--------|-------------|
| **Switch** | Shower | Simple on/off control |
| **Water Heater** | Shower | Full control with target temperature and operation mode |
| **Sensor** | Live Temperature | Current water temperature (°C) |
| **Sensor** | Target Temperature | Requested temperature (°C) |
| **Sensor** | Flow Rate | Current flow rate (Min/Med/Max) |
| **Sensor** | Running Time | Elapsed running time (seconds) |
| **Sensor** | Temperature State | Warming / Cooling / At Temperature |
| **Binary Sensor** | Online | Shower connectivity status |
| **Binary Sensor** | Running | Whether the shower is currently running |
| **Select** | Flow Rate | Choose flow rate: Min, Med, or Max |
| **Select** | Outlet | Choose outlet (if multiple outlets are configured) |
| **Number** | Max Duration | Maximum shower duration (60–3600 seconds) |

### Real-Time Updates

This integration uses **Firebase Cloud Messaging (FCM)** to receive push notifications directly from the Aqualisa cloud. Entity states update instantly when the shower is operated from any source — the physical controls, the Aqualisa app, or Home Assistant itself.

### Multi-Factor Authentication

The config flow supports Aqualisa accounts with MFA enabled (SMS or Email verification).

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right and select **Custom repositories**
3. Add `https://github.com/hmchan/hass-aqualisa` with category **Integration**
4. Search for "Aqualisa" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/aqualisa` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **Aqualisa Smart Shower**
3. Enter your Aqualisa account email and password
4. Select your region (UK or EU)
5. If MFA is enabled, choose your verification method and enter the code

## Automation Examples

### Turn on the shower at a scheduled time

```yaml
automation:
  - alias: "Morning shower"
    trigger:
      - platform: time
        at: "06:30:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.aqualisa_shower_shower
```

### Notify when the shower reaches target temperature

```yaml
automation:
  - alias: "Shower ready notification"
    trigger:
      - platform: state
        entity_id: sensor.aqualisa_shower_temperature_state
        to: "At Temperature"
    action:
      - service: notify.mobile_app
        data:
          message: "Your shower is ready!"
```

### Auto-off safety timer

```yaml
automation:
  - alias: "Shower auto-off after 15 minutes"
    trigger:
      - platform: state
        entity_id: binary_sensor.aqualisa_shower_running
        to: "on"
        for:
          minutes: 15
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.aqualisa_shower_shower
```

## Translations

The integration UI is available in:
English, Traditional Chinese (繁體中文), Japanese (日本語), French, German, Spanish, Italian, and Portuguese.

## Troubleshooting

### Live status not updating
The integration registers as an FCM receiver with the Aqualisa cloud. If live updates stop working, try reloading the integration from **Settings** > **Devices & Services** > **Aqualisa** > **Reload**.

### Network errors at startup
Transient network errors during startup are handled automatically with up to 10 retries with exponential backoff.

### Token expiry
If your session expires, the integration will attempt to re-authenticate using stored credentials. If this fails, you may need to reconfigure the integration.

## License

MIT

## Disclaimer

This integration is not affiliated with or endorsed by Aqualisa. Use at your own risk.
