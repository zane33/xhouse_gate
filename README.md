# X-House IOT Gate Controller

A lightweight Python HTTP server that wraps the X-House IOT cloud API, giving you simple REST endpoints to **open**, **close**, and **check the status** of your gate — no app required.

Built by reverse-engineering the X-House IOT Android app's network traffic (credit to [BenJamesAndo](https://github.com/BenJamesAndo) for the original AppDaemon gist). The server maintains a persistent TCP session to the X-House cloud, authenticates with your account credentials, auto-discovers your gate device, and translates simple HTTP calls into the proprietary SET_MENU BLE-over-WiFi protocol.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [API Reference](#api-reference)
  - [Health Check](#health-check)
  - [Gate Status](#gate-status)
  - [Open Gate](#open-gate)
  - [Close Gate](#close-gate)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Docker](#docker)
  - [Build and Run](#build-and-run)
  - [Docker Compose](#docker-compose)
- [Deploy via Portainer](#deploy-via-portainer)
  - [Option A — Portainer Stacks (Recommended)](#option-a--portainer-stacks-recommended)
  - [Option B — Portainer Git Deploy](#option-b--portainer-git-deploy)
- [Home Automation Integration](#home-automation-integration)
  - [Home Assistant](#home-assistant)
  - [Generic Webhook / cURL](#generic-webhook--curl)
- [How It Works](#how-it-works)
- [Supported Devices](#supported-devices)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- Single-file Python server (`server.py`) with minimal dependencies (Flask + Requests)
- Automatic login, token refresh, and device discovery
- Thread-safe command execution
- Lightweight Docker image based on `python:3.11-slim`
- Ready-made `docker-compose.yml` for one-command deployment
- Drop-in compatible with Portainer Stacks

---

## Prerequisites

- An **X-House IOT** account (the same email/password you use in the X-House app)
- A WiFi+BLE gate controller paired and online in X-House IOT (e.g. XH-SGC01)
- **Python 3.10+** (if running locally) or **Docker** (recommended)

---

## API Reference

The server listens on port `8765` by default. All responses are JSON.

### Health Check

```
GET /health
```

Returns the server's internal state — useful for monitoring and readiness probes.

**Response:**

```json
{
  "status": "ok",
  "logged_in": true,
  "device_id": "123456",
  "ble_code": "95432482",
  "device": "Front Gate"
}
```

### Gate Status

```
GET /status
```

Queries the X-House cloud for the current gate position.

**Response:**

```json
{ "state": "open" }
```

| `state`    | Meaning                       |
|------------|-------------------------------|
| `"open"`   | Gate is fully open            |
| `"closed"` | Gate is fully closed          |
| `"unknown"`| Could not determine (+ error) |

### Open Gate

```
POST /open
```

Sends the open command sequence (SET_MENU steps 1 & 2).

**Response:**

```json
{ "success": true }
```

### Close Gate

```
POST /close
```

Sends the close command sequence (SET_MENU steps 1 & 2).

**Response:**

```json
{ "success": true }
```

---

## Configuration

All configuration is done through environment variables:

| Variable          | Required | Default | Description                              |
|-------------------|----------|---------|------------------------------------------|
| `XHOUSE_EMAIL`    | Yes      | —       | Your X-House IOT account email           |
| `XHOUSE_PASSWORD` | Yes      | —       | Your X-House IOT account password        |
| `PORT`            | No       | `8765`  | HTTP port the server listens on          |

---

## Running Locally

```bash
# Install dependencies
pip install flask requests

# Set credentials
export XHOUSE_EMAIL="you@example.com"
export XHOUSE_PASSWORD="your-password"

# Start the server
python server.py
```

The server will start on `http://localhost:8765`.

---

## Docker

### Build and Run

```bash
docker build -t xhouse-gate .

docker run -d \
  --name xhouse-gate \
  --restart always \
  -p 8765:8765 \
  -e XHOUSE_EMAIL="you@example.com" \
  -e XHOUSE_PASSWORD="your-password" \
  xhouse-gate
```

### Docker Compose

```bash
# Set your credentials (or add them to a .env file)
export XHOUSE_EMAIL="you@example.com"
export XHOUSE_PASSWORD="your-password"

docker compose up -d
```

Or create a `.env` file in the project root:

```env
XHOUSE_EMAIL=you@example.com
XHOUSE_PASSWORD=your-password
```

Then simply:

```bash
docker compose up -d
```

---

## Deploy via Portainer

### Option A — Portainer Stacks (Recommended)

This is the easiest way to deploy if you already have Portainer managing your Docker host.

1. Open **Portainer** and navigate to **Stacks** > **Add Stack**
2. Give it a name, e.g. `xhouse-gate`
3. Select **Web editor** and paste the following compose definition:

```yaml
services:
  xhouse-gate:
    build: .
    container_name: xhouse-gate
    restart: always
    ports:
      - "8765:8765"
    environment:
      - XHOUSE_EMAIL=you@example.com
      - XHOUSE_PASSWORD=your-password
      - PORT=8765
```

> **Note:** If your Portainer host does not have the source code to build from, use a pre-built image instead. Push the image to a registry first:
>
> ```bash
> docker build -t your-registry/xhouse-gate:latest .
> docker push your-registry/xhouse-gate:latest
> ```
>
> Then replace the `build: .` line with:
>
> ```yaml
>     image: your-registry/xhouse-gate:latest
> ```

4. Scroll down to **Environment variables** (alternatively, hard-code them in the YAML above)
5. Click **Deploy the stack**

The container will start automatically and restart on failure or host reboot.

### Option B — Portainer Git Deploy

If your repository is hosted on GitHub/GitLab and accessible from the Portainer host:

1. Go to **Stacks** > **Add Stack**
2. Select **Repository**
3. Fill in:
   - **Repository URL** — your git repo URL
   - **Compose path** — `docker-compose.yml`
4. Under **Environment variables**, add:
   - `XHOUSE_EMAIL` = your email
   - `XHOUSE_PASSWORD` = your password
5. Click **Deploy the stack**

Portainer will clone the repo, build the image, and start the container. You can enable **GitOps updates** to auto-redeploy on push.

---

## Home Automation Integration

### Home Assistant

Add the following to your `configuration.yaml` to create a gate cover entity using the [REST](https://www.home-assistant.io/integrations/rest/), [RESTful Command](https://www.home-assistant.io/integrations/rest_command/), and [Template](https://www.home-assistant.io/integrations/template/) integrations.

The `input_number.front_gate_transition_time` lets you configure how long (in seconds) the gate takes to fully open or close. During this window the cover will show as "opening" or "closing" in Home Assistant.

```yaml
# Transition time (seconds) — adjust to match your gate's travel time
input_number:
  front_gate_transition_time:
    name: Front Gate Transition Time
    min: 5
    max: 120
    step: 1
    initial: 30
    unit_of_measurement: "s"

# Timer used to track opening/closing transition
timer:
  front_gate_transition:
    name: Front Gate Transition

# Sensor to poll gate status
rest:
  - resource: http://<server-ip>:8765/status
    scan_interval: 30
    sensor:
      - name: "Front Gate Status"
        value_template: "{{ value_json.state }}"

# Commands to open/close the gate
rest_command:
  open_front_gate:
    url: http://<server-ip>:8765/open
    method: post
  close_front_gate:
    url: http://<server-ip>:8765/close
    method: post

# Template cover with transition states
template:
  - cover:
      - name: Front Gate
        device_class: gate
        state: >
          {% if is_state('timer.front_gate_transition', 'active') %}
            {{ states('input_text.front_gate_direction') }}
          {% else %}
            {{ states('sensor.front_gate_status') }}
          {% endif %}
        open_cover:
          - action: rest_command.open_front_gate
          - action: timer.start
            target:
              entity_id: timer.front_gate_transition
            data:
              duration: "{{ states('input_number.front_gate_transition_time') | int }}"
          - action: input_text.set_value
            target:
              entity_id: input_text.front_gate_direction
            data:
              value: opening
        close_cover:
          - action: rest_command.close_front_gate
          - action: timer.start
            target:
              entity_id: timer.front_gate_transition
            data:
              duration: "{{ states('input_number.front_gate_transition_time') | int }}"
          - action: input_text.set_value
            target:
              entity_id: input_text.front_gate_direction
            data:
              value: closing

# Helper to track the direction of the current transition
input_text:
  front_gate_direction:
    name: Front Gate Direction
    initial: ""
```

> **Note:** Adjust the `front_gate_transition_time` initial value to match how long your gate takes to travel. The cover state will show "opening"/"closing" during this period, then revert to the REST sensor's reported state.

Replace `<server-ip>` with the IP or hostname of the machine running the container.

### Generic Webhook / cURL

```bash
# Check status
curl http://localhost:8765/status

# Open the gate
curl -X POST http://localhost:8765/open

# Close the gate
curl -X POST http://localhost:8765/close

# Health check
curl http://localhost:8765/health
```

These endpoints can be called from any automation platform, script, or shortcut (e.g. iOS Shortcuts, Tasker, Node-RED, n8n).

---

## How It Works

1. **Login** — Authenticates against the X-House cloud API using your email and password. Receives a session token.
2. **Device Discovery** — Queries your account's device list and identifies the gate by matching model/alias keywords (e.g. `gate`, `xh-sgc01`, `sliding`).
3. **BLE Code Extraction** — Reads the 8-character BLE hex code from the device's properties. This code is embedded in every control command.
4. **Command Protocol** — Sends two-step SET_MENU commands via the `/wifi/sendWifiCode` endpoint:
   - Step 1: `3A{bleCode}{cmdByte}01` (initiate)
   - Step 2: `3A{bleCode}{cmdByte}02` (confirm)
   - Command bytes: `03` = open, `04` = close
5. **Log Upload** — Mirrors the app's behaviour by uploading a control log entry after each command.
6. **Token Refresh** — Automatically detects expired tokens and re-authenticates.

---

## Supported Devices

This server was built and tested with WiFi+BLE sliding gate controllers from Giant Auto Gate / X-House IOT. Known compatible models:

- **XH-SGC01** — WiFi+BLE Sliding Gate Controller

Other X-House IOT gate devices (swing, barrier, garage) may work if they use the same SET_MENU protocol. The server auto-discovers devices matching these keywords: `gate`, `xh-sgc01`, `sgc01`, `sliding`, `swing`, `barrier`, `wifi+ble`, `garage`, `door`.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `XHOUSE_EMAIL and XHOUSE_PASSWORD must be set!` | Ensure both environment variables are set before starting |
| `Login error: ...` | Verify your credentials work in the X-House app first |
| `No gate device found` | Ensure your gate controller is online and paired in the X-House app |
| `bleCode not found in device properties` | The device was found but its BLE code wasn't in the expected property keys — check the `/health` endpoint for device info |
| `token invalid` errors | The server handles this automatically by re-authenticating. If persistent, restart the container |
| Gate doesn't move but API returns success | The cloud accepted the command but the physical controller may be offline or out of range of your WiFi |

---

## License

This project is provided as-is for personal and educational use. It is not affiliated with or endorsed by Giant Auto Gate, X-House IOT, or any related entity.
