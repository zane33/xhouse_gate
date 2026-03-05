# Home Assistant Integration

This guide covers setting up the X-House IOT Gate as a **Cover** entity in Home Assistant (Core installation), using the locally running container as a bridge.

## Prerequisites

- Home Assistant Core running and accessible
- The `xhouse_gate` container running on your local network (e.g. `192.168.3.148:8765`)
- The container's `/health` endpoint returning `"logged_in": true`

## Configuration

Add the following to your `configuration.yaml`:

```yaml
rest_command:
  xhouse_gate_open:
    url: "http://192.168.3.148:8765/open"
    method: POST
  xhouse_gate_close:
    url: "http://192.168.3.148:8765/close"
    method: POST

cover:
  - platform: template
    covers:
      xhouse_gate:
        device_class: gate
        friendly_name: "Sliding Gate"
        value_template: >
          {{ states('sensor.xhouse_gate_state') }}
        open_cover:
          action: rest_command.xhouse_gate_open
        close_cover:
          action: rest_command.xhouse_gate_close
        stop_cover:
          # The X-House gate does not support a stop command
          action: rest_command.xhouse_gate_open
```

## State Sensor

Add a REST sensor to poll the gate status:

```yaml
sensor:
  - platform: rest
    name: "X-House Gate State"
    resource: "http://192.168.3.148:8765/status"
    value_template: "{{ value_json.state }}"
    scan_interval: 30
```

This creates `sensor.xhouse_gate_state` which the cover template references. The `scan_interval` controls how often (in seconds) Home Assistant polls the gate status. Adjust as needed — lower values give faster feedback but increase API traffic.

## How It Works

The template cover maps Home Assistant's cover actions to the local server:

| Cover Action  | Server Endpoint | Gate Behaviour |
| ------------- | --------------- | -------------- |
| Open          | `POST /open`    | Opens the gate |
| Close         | `POST /close`   | Closes the gate|

The cover state is derived from the REST sensor:

| Sensor Value | Cover State |
| ------------ | ----------- |
| `open`       | `open`      |
| `closed`     | `closed`    |
| `unknown`    | `unknown`   |

## Full configuration.yaml Example

```yaml
rest_command:
  xhouse_gate_open:
    url: "http://192.168.3.148:8765/open"
    method: POST
  xhouse_gate_close:
    url: "http://192.168.3.148:8765/close"
    method: POST

sensor:
  - platform: rest
    name: "X-House Gate State"
    resource: "http://192.168.3.148:8765/status"
    value_template: "{{ value_json.state }}"
    scan_interval: 30

cover:
  - platform: template
    covers:
      xhouse_gate:
        device_class: gate
        friendly_name: "Sliding Gate"
        value_template: >
          {{ states('sensor.xhouse_gate_state') }}
        open_cover:
          action: rest_command.xhouse_gate_open
        close_cover:
          action: rest_command.xhouse_gate_close
```

## Validation and Restart

1. Validate your configuration:
   - Go to **Developer Tools** > **YAML** > **Check Configuration**
   - Or run: `hass --script check_config`

2. Restart Home Assistant:
   - Go to **Developer Tools** > **YAML** > **Restart**
   - Or run: `ha core restart`

3. Verify the entities exist:
   - `cover.xhouse_gate` should appear under **Developer Tools** > **States**
   - `sensor.xhouse_gate_state` should show `open` or `closed`

## Optional: Health Check as a Binary Sensor

You can monitor the container's health as a binary sensor:

```yaml
binary_sensor:
  - platform: rest
    name: "X-House Gate Server"
    resource: "http://192.168.3.148:8765/health"
    value_template: "{{ value_json.logged_in }}"
    device_class: connectivity
    scan_interval: 60
```

This will show as `on` when the server is logged in and `off` if the session has dropped.

## Automations

Example automation to close the gate at night:

```yaml
automation:
  - alias: "Close gate at night"
    trigger:
      - platform: time
        at: "22:00:00"
    condition:
      - condition: state
        entity_id: cover.xhouse_gate
        state: "open"
    action:
      - action: cover.close_cover
        target:
          entity_id: cover.xhouse_gate
```

## Troubleshooting

| Problem                         | Check                                                        |
| ------------------------------- | ------------------------------------------------------------ |
| Cover shows `unknown`           | Verify `sensor.xhouse_gate_state` has a value in Developer Tools > States |
| Sensor shows `unknown`          | Check the container is reachable: `curl http://192.168.3.148:8765/status` |
| Open/close does nothing         | Check container logs; verify `/health` shows `logged_in: true` |
| `rest_command` not found        | Restart Home Assistant after adding the configuration         |
| State lags behind actual gate   | Reduce `scan_interval` on the REST sensor (e.g. `10`)        |

## Notes

- The server IP (`192.168.3.148`) should be static or reserved via DHCP to avoid connectivity issues.
- The container handles token refresh automatically — if the upstream session expires, it will re-login on the next request.
- The REST sensor polls on an interval. The cover state won't update instantly after a command — it will reflect the change on the next poll cycle.
