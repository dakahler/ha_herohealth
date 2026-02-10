# Hero Health for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration for [Hero Health](https://herohealth.com/) smart medication dispensers. Monitor your Hero device, medication adherence, next dose times, and pill supply levels directly from Home Assistant.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** > **Custom repositories**
3. Add `https://github.com/dakahler/ha_herohealth` as a custom repository (category: Integration)
4. Search for "Hero Health" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/herohealth` folder into your Home Assistant `custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **Hero Health**
3. Enter your Hero Health email and password (the same credentials you use in the mobile app)

## Sensors

### Device

| Entity | Type | Description |
|--------|------|-------------|
| Device Online | Binary sensor | Whether the Hero dispenser is reachable |

### Medications

| Entity | Type | Description |
|--------|------|-------------|
| Next Dose | Timestamp | Time of the next scheduled dose |
| Last Event | Timestamp | Most recent dispensing event |
| Doses Taken Today | Count | Number of doses taken today |
| *{Pill Name}* Remaining Days | Days | Days of supply remaining (one per medication slot) |

### Attributes

Each sensor exposes additional attributes:

- **Next Dose**: pill names, pill count
- **Last Event**: status, pill source, pill names
- **Doses Taken Today**: total/missed/pending counts for today
- **Remaining Days**: slot index, pill name, days min/max, pill count, error
- **Device Online**: timezone offset, travel mode

## Example Automations

### Notify When It's Time to Take Medication

```yaml
automation:
  - alias: "Medication Reminder"
    trigger:
      - platform: template
        value_template: >
          {{ (as_timestamp(states('sensor.hero_health_dispenser_next_dose')) - as_timestamp(now())) < 300 }}
    condition:
      - condition: template
        value_template: >
          {{ states('sensor.hero_health_dispenser_next_dose') not in ['unknown', 'unavailable'] }}
    action:
      - service: notify.mobile_app
        data:
          title: "Medication Reminder"
          message: >
            Time to take your medication:
            {{ state_attr('sensor.hero_health_dispenser_next_dose', 'pills') }}
```

### Alert on Missed Doses

```yaml
automation:
  - alias: "Missed Dose Alert"
    trigger:
      - platform: state
        entity_id: sensor.hero_health_dispenser_doses_taken_today
    condition:
      - condition: template
        value_template: >
          {{ state_attr('sensor.hero_health_dispenser_doses_taken_today', 'missed_today') | int > 0 }}
    action:
      - service: notify.mobile_app
        data:
          title: "Missed Dose"
          message: >
            {{ state_attr('sensor.hero_health_dispenser_doses_taken_today', 'missed_today') }} dose(s) missed today.
```

### Notify Caregiver When Device Goes Offline

```yaml
automation:
  - alias: "Hero Device Offline"
    trigger:
      - platform: state
        entity_id: binary_sensor.hero_health_dispenser_device_online
        to: "off"
        for:
          minutes: 30
    action:
      - service: notify.mobile_app
        data:
          title: "Hero Health Offline"
          message: "The Hero medication dispenser has been offline for 30 minutes."
```

### Dashboard Card

```yaml
type: entities
title: Medications
entities:
  - entity: sensor.hero_health_dispenser_next_dose
    name: Next Dose
  - entity: sensor.hero_health_dispenser_doses_taken_today
    name: Doses Taken Today
  - entity: sensor.hero_health_dispenser_last_event
    name: Last Event
  - entity: binary_sensor.hero_health_dispenser_device_online
    name: Device Online
```

## Polling

Data updates every **5 minutes**. Medication events are time-sensitive, so a shorter interval is used compared to typical integrations.

## Authentication

The integration authenticates using the same OAuth2 flow as the Hero Health mobile app. Your credentials are used once during setup to obtain tokens. Only a refresh token is stored — your password is never saved. Tokens are automatically refreshed as needed.

## Troubleshooting

### "Invalid email or password"
Verify your credentials work in the Hero Health mobile app. The integration uses the same login system.

### Sensors show "unavailable"
Check the Home Assistant logs for `herohealth` entries. The API response format may have changed — please open an issue with the relevant log output.

### Remaining Days shows "Unknown"
The Hero device needs to know how many pills are in each slot to calculate remaining days. This is populated after a pill count or refill through the Hero app.

### Re-authentication required
If your refresh token expires (e.g., after a long HA downtime), Home Assistant will prompt you to re-authenticate via the Integrations page.

## License

MIT
