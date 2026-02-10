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
| Device Online | Binary sensor | Whether the Hero dispenser is connected |

### Medications

| Entity | Type | Description |
|--------|------|-------------|
| Next Dose | Timestamp | Time of the next scheduled dose |
| Medication Adherence | Percentage | Overall medication adherence rate |
| Last Event | Timestamp | Most recent device event |
| Doses Taken Today | Count | Number of doses taken today |
| *{Pill Name}* Remaining Days | Days | Days of supply remaining (one per medication slot) |

### Attributes

Each sensor exposes additional attributes:

- **Next Dose**: pill names, pill count
- **Medication Adherence**: taken/missed/total counts, period
- **Last Event**: event type, details, pill names
- **Doses Taken Today**: total/missed/pending counts for today
- **Remaining Days**: slot index, pill name, pills remaining, pills per day
- **Device Online**: firmware version, device ID

## Polling

Data updates every **5 minutes**. Medication events are time-sensitive, so a shorter interval is used compared to typical integrations.

## Authentication

The integration authenticates using the same OAuth2 flow as the Hero Health mobile app. Your credentials are used once during setup to obtain tokens. Only a refresh token is stored — your password is never saved. Tokens are automatically refreshed as needed.

## Troubleshooting

### "Invalid email or password"
Verify your credentials work in the Hero Health mobile app. The integration uses the same login system.

### Sensors show "unavailable"
Check the Home Assistant logs for `herohealth` entries. The API response format may have changed — please open an issue with the relevant log output.

### Re-authentication required
If your refresh token expires (e.g., after a long HA downtime), Home Assistant will prompt you to re-authenticate via the Integrations page.

## License

MIT
