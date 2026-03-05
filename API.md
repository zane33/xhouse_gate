# API Documentation

## Local Server API

The local Flask server (`server.py`) provides a simplified HTTP interface for controlling an X-House IOT gate. It handles authentication, device discovery, and command formatting internally.

**Base URL:** `http://localhost:8765` (configurable via `PORT` env var)

### Environment Variables

| Variable         | Required | Default | Description                     |
| ---------------- | -------- | ------- | ------------------------------- |
| `XHOUSE_EMAIL`   | Yes      |         | X-House account email           |
| `XHOUSE_PASSWORD`| Yes      |         | X-House account password        |
| `PORT`           | No       | `8765`  | Port the server listens on      |

---

### `GET /health`

Returns the server's internal session state.

**Response `200`:**
```json
{
  "status": "ok",
  "logged_in": true,
  "device_id": "959534190116737024",
  "ble_code": "95432482",
  "device": "Sliding Gate"
}
```

| Field       | Type          | Description                                      |
| ----------- | ------------- | ------------------------------------------------ |
| `status`    | `string`      | Always `"ok"`                                    |
| `logged_in` | `boolean`     | Whether the upstream token is present             |
| `device_id` | `string|null` | Discovered gate device ID, or `null`              |
| `ble_code`  | `string|null` | 8-char hex BLE code from device properties        |
| `device`    | `string|null` | Device alias or model name                        |

---

### `GET /status`

Returns the current gate state by querying the upstream API.

**Response `200`:**
```json
{
  "state": "open"
}
```

| Field   | Type     | Values                                                      |
| ------- | -------- | ----------------------------------------------------------- |
| `state` | `string` | `"open"` (Switch_1=1), `"closed"` (Switch_1=0 or other)    |

**Response `503`:**
```json
{
  "state": "unknown",
  "error": "session failed"
}
```

---

### `POST /open`

Opens the gate.

**Response `200`:**
```json
{
  "success": true
}
```

**Response `500`:**
```json
{
  "success": false,
  "error": "Open failed: <message>"
}
```

**Response `503`:**
```json
{
  "success": false,
  "error": "session failed"
}
```

---

### `POST /close`

Closes the gate.

**Response `200`:**
```json
{
  "success": true
}
```

**Response `500`:**
```json
{
  "success": false,
  "error": "Close failed: <message>"
}
```

**Response `503`:**
```json
{
  "success": false,
  "error": "session failed"
}
```

---

## Upstream X-House IOT API

The upstream cloud API used by the X-House IOT mobile app.

**Base URL:** `https://xhouseiot.giantautogate.com/xhouseAppEncapsulation`

### Authentication

All requests require HMAC-signed headers. Authenticated endpoints additionally require `token` and `userId` headers.

#### Required Headers (all requests)

| Header         | Value                                                                 |
| -------------- | --------------------------------------------------------------------- |
| `apptype`      | `"android"`                                                           |
| `l`            | `"EN"` (language)                                                     |
| `phonetime`    | Current datetime, e.g. `"2026-03-05 14:30:00"`                       |
| `platformcode` | `"giigle"`                                                            |
| `saascode`     | `"JUJIANG"`                                                           |
| `timestamp`    | Unix timestamp as string                                              |
| `signature`    | HMAC-MD5 of `platformcode + timestamp` using key `juge2020@giigleiot` |
| `content-type` | `"application/json; charset=utf-8"`                                   |

#### Additional Headers (authenticated requests)

| Header   | Value                  |
| -------- | ---------------------- |
| `token`  | Token from login       |
| `userid` | User ID from login     |

#### Signature Generation

```
signature = HMAC-MD5(key="juge2020@giigleiot", message="giigle" + timestamp)
```

The result is a 32-char lowercase hex digest.

---

### Standard Response Envelope

All upstream responses use this format:

```json
{
  "code": "0",
  "msg": "success!",
  "errorMap": null,
  "result": ...
}
```

| Field      | Type          | Description                                        |
| ---------- | ------------- | -------------------------------------------------- |
| `code`     | `string`      | `"0"` = success, other values indicate errors      |
| `msg`      | `string`      | Human-readable message (may be unicode-escaped)     |
| `errorMap` | `object|null` | Error details, usually `null`                       |
| `result`   | `any`         | Response payload, type varies by endpoint           |

---

### `POST /clientUser/login`

Authenticates a user and returns a session token.

**Request Body:**
```json
{
  "saasCode": "JUJIANG",
  "type": "EMAIL",
  "email": "user@example.com",
  "password": "password123",
  "appType": "ANDROID"
}
```

**Result:**
```json
{
  "token": "b7b136f866ad95e0",
  "userId": "1041077682399350784"
}
```

The `token` and `userId` are required for all subsequent authenticated requests.

---

### `POST /group/queryGroupDevices`

Lists all devices associated with the user's account.

**Request Body:**
```json
{
  "userId": "1041077682399350784",
  "groupId": 0
}
```

**Result:**
```json
{
  "deviceInfos": [
    {
      "id": 959534190116737024,
      "alias": "Sliding Gate",
      "model": "XH-SGC01",
      "properties": [
        { "key": "bleCode", "value": "95432482" },
        { "key": "Switch_1", "value": "0" }
      ]
    }
  ]
}
```

| Field                    | Type     | Description                                          |
| ------------------------ | -------- | ---------------------------------------------------- |
| `deviceInfos[].id`      | `number` | Device ID (use as string in subsequent requests)     |
| `deviceInfos[].alias`   | `string` | User-assigned device name                            |
| `deviceInfos[].model`   | `string` | Device model identifier                              |
| `deviceInfos[].properties` | `array` | Key-value pairs including `bleCode`, `Switch_1`, etc |

The `bleCode` property (8-char hex string, e.g. `"95432482"`) is required for building gate commands.

---

### `POST /wifi/getWifiProperties`

Returns the current state/properties of a device.

**Request Body:**
```json
{
  "userId": "1041077682399350784",
  "deviceId": "959534190116737024"
}
```

**Result:**
```json
{
  "properties": [
    { "key": "Switch_1", "value": "0" }
  ]
}
```

| `Switch_1` Value | Meaning        |
| ----------------- | -------------- |
| `"0"`             | Fully closed   |
| `"1"`             | Fully open     |
| `"2"`             | Stopped/moving |

---

### `POST /wifi/sendWifiCode`

Sends a control command to a WiFi+BLE gate device using the SET_MENU protocol.

**Request Body:**
```json
{
  "deviceId": "959534190116737024",
  "propertyValue": {
    "type": "SET_MENU",
    "object": {
      "value": "3A954324820401"
    }
  },
  "userId": "1041077682399350784",
  "action": ""
}
```

**Result (string):**
```
"3A9543248201"
```

#### SET_MENU Value Format

The `value` field is a 14-character hex string:

```
3A | bleCode  | cmdByte | actionByte
3A | 95432482 | 04      | 01
```

| Segment      | Length  | Description                                     |
| ------------ | ------- | ----------------------------------------------- |
| Prefix       | 2 chars | Always `"3A"`                                   |
| `bleCode`    | 8 chars | BLE identifier from device properties            |
| `cmdByte`    | 2 chars | Command type, `"04"` for gate control            |
| `actionByte` | 2 chars | `"01"` = open, `"02"` = close                   |

#### Confirmed Commands (from mitmproxy captures)

| Action | Value              | Response         |
| ------ | ------------------ | ---------------- |
| Open   | `3A954324820401`   | `3A9543248201`   |
| Close  | `3A954324820402`   | `3A9543248202`   |

---

### `POST /bluetooth/uploadBluetoothControlLog`

Uploads a control log entry. The mobile app sends this after each gate command.

**Request Body:**
```json
{
  "action": "Open",
  "deviceId": "959534190116737024"
}
```

| Field      | Type     | Description                       |
| ---------- | -------- | --------------------------------- |
| `action`   | `string` | `"Open"` or `"Close"`            |
| `deviceId` | `string` | Target device ID                  |

**Result:** Unspecified (logged but not used).
