#!/usr/bin/env python3
"""
X-House IOT Gate Server
Uses a persistent requests.Session() to maintain the same TCP connection
as the original AppDaemon gist by BenJamesAndo.

Endpoints:
  GET  /status   -> {"state": "open"} or {"state": "closed"}
  POST /open     -> opens the gate
  POST /close    -> closes the gate
  GET  /health   -> {"status": "ok"}
"""

import hashlib
import hmac
import json
import logging
import os
import time
import requests
from datetime import datetime
from threading import Lock

from flask import Flask, jsonify

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE_URL  = "https://xhouseiot.giantautogate.com/xhouseAppEncapsulation"
HMAC_SECRET   = "juge2020@giigleiot"
SAAS_CODE     = "JUJIANG"
PLATFORM_CODE = "giigle"
APP_TYPE      = "android"

EMAIL    = os.environ.get("XHOUSE_EMAIL", "")
PASSWORD = os.environ.get("XHOUSE_PASSWORD", "")
PORT     = int(os.environ.get("PORT", "8765"))

GATE_KEYWORDS = ["gate", "xh-sgc01", "sgc01", "sliding", "swing", "barrier", "wifi+ble", "garage", "door"]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app  = Flask(__name__)
lock = Lock()

# ── Persistent session (critical - matches original gist behaviour) ───────────
http = requests.Session()

session = {
    "token":     None,
    "user_id":   None,
    "device_id": None,
    "device":    None,
    "ble_code":  None,   # 8-char hex code used in SET_MENU commands (e.g. "95432482")
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_signature():
    timestamp    = str(int(time.time()))
    data_to_sign = PLATFORM_CODE + timestamp
    signature    = hmac.new(
        HMAC_SECRET.encode("utf-8"),
        data_to_sign.encode("utf-8"),
        hashlib.md5,
    ).hexdigest()
    return signature, timestamp


def base_headers(token=None, user_id=None):
    signature, timestamp = generate_signature()
    headers = {
        "apptype":      APP_TYPE,
        "l":            "EN",
        "phonetime":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platformcode": PLATFORM_CODE,
        "saascode":     SAAS_CODE,
        "timestamp":    timestamp,
        "signature":    signature,
        "content-type": "application/json; charset=utf-8",
        "user-agent":   "okhttp/4.2.0",
        "host":         "xhouseiot.giantautogate.com",
        "connection":   "Keep-Alive",
    }
    if token:
        headers["token"]  = token
        headers["userid"] = str(user_id)
    return headers


def api_post(path, body, token=None, user_id=None):
    body_string = json.dumps(body, separators=(",", ":"))
    headers     = base_headers(token, user_id)
    headers["content-length"] = str(len(body_string.encode("utf-8")))
    try:
        response = http.post(
            f"{API_BASE_URL}{path}",
            headers=headers,
            data=body_string,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error("API error on %s: %s", path, e)
        return None


def decode_msg(msg):
    if not msg:
        return msg
    try:
        return msg.encode().decode("unicode_escape").encode("latin1").decode("utf-8")
    except Exception:
        return msg


# ── Auth & discovery ──────────────────────────────────────────────────────────

def do_login():
    log.info("Logging in as %s...", EMAIL)
    body = {
        "saasCode": SAAS_CODE,
        "type":     "EMAIL",
        "email":    EMAIL,
        "password": PASSWORD,
        "appType":  APP_TYPE.upper(),
    }
    body_string = json.dumps(body, separators=(",", ":"))
    headers     = base_headers()
    headers["content-length"] = str(len(body_string.encode("utf-8")))
    try:
        response = http.post(
            f"{API_BASE_URL}/clientUser/login",
            headers=headers,
            data=body_string,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        log.error("Login request failed: %s", e)
        return False

    if data.get("code") == "0":
        session["token"]   = data["result"]["token"]
        session["user_id"] = data["result"]["userId"]
        log.info("Login successful. User ID: %s", session["user_id"])
        return True

    log.error("Login error: %s", decode_msg(data.get("msg")))
    return False


def discover_device():
    data = api_post(
        "/group/queryGroupDevices",
        {"userId": session["user_id"], "groupId": 0},
        token=session["token"],
        user_id=session["user_id"],
    )
    if not data or data.get("code") != "0":
        log.error("Device discovery failed: %s", decode_msg(data.get("msg") if data else "no response"))
        return False

    devices = data.get("result", {}).get("deviceInfos", [])
    log.info("Devices: %s", [d.get("alias") or d.get("model") for d in devices])

    for device in devices:
        model = (device.get("model") or "").lower()
        alias = (device.get("alias") or "").lower()
        if any(k in model or k in alias for k in GATE_KEYWORDS):
            session["device_id"] = str(device["id"])
            session["device"]    = device

            # Extract bleCode from device properties (used in SET_MENU commands)
            ble_code = None
            for prop in device.get("properties", []):
                if prop.get("key", "").lower() in ("blecode", "ble_code", "bleaddr", "ble"):
                    ble_code = prop.get("value", "")
                    break
            if ble_code:
                session["ble_code"] = ble_code
                log.info("bleCode from properties: %s", ble_code)
            else:
                log.warning("bleCode not found in properties — will derive from first command response")

            log.info("Using device: %s (id=%s) properties=%s",
                     device.get("alias") or device.get("model"),
                     session["device_id"],
                     device.get("properties", []))
            return True

    log.error("No gate device found")
    return False


def ensure_session():
    if not session["token"]:
        if not do_login():
            return False
    if not session["device_id"]:
        if not discover_device():
            return False
    return True


def handle_token_expiry(msg):
    if msg and "token invalid" in msg.lower():
        log.warning("Token expired, will re-login")
        session["token"] = None
        return True
    return False


# ── Startup ───────────────────────────────────────────────────────────────────

def startup():
    if not EMAIL or not PASSWORD:
        log.error("XHOUSE_EMAIL and XHOUSE_PASSWORD must be set!")
        return
    with lock:
        do_login()
        if session["token"]:
            discover_device()


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":    "ok",
        "logged_in": session["token"] is not None,
        "device_id": session.get("device_id"),
        "ble_code":  session.get("ble_code"),
        "device":    (session["device"].get("alias") or session["device"].get("model")) if session.get("device") else None,
    })


@app.route("/status", methods=["GET"])
def status():
    with lock:
        if not ensure_session():
            return jsonify({"state": "unknown", "error": "session failed"}), 503

        data = api_post(
            "/wifi/getWifiProperties",
            {"userId": session["user_id"], "deviceId": session["device_id"]},
            token=session["token"],
            user_id=session["user_id"],
        )

        if not data or data.get("code") != "0":
            msg = decode_msg(data.get("msg", "")) if data else "no response"
            handle_token_expiry(msg)
            return jsonify({"state": "unknown", "error": msg}), 503

        properties = data.get("result", {}).get("properties", [])
        log.info("Raw properties: %s", properties)

        state = "unknown"
        for prop in properties:
            if prop.get("key") == "Switch_1":
                val = prop.get("value")
                # Switch_1: "0" = closed, "2" = open (confirmed via API capture)
                if val == "2":
                    state = "open"
                elif val == "0":
                    state = "closed"
                else:
                    state = "unknown"
                log.info("Switch_1 raw value: %s -> state=%s", val, state)
                break
        # Build response with all properties except Switch_1 (already mapped to state)
        result = {"state": state}
        for prop in properties:
            key = prop.get("key")
            if key and key != "Switch_1":
                result[key] = prop.get("value")

        log.info("Status: %s", state)
        return jsonify(result)


@app.route("/open", methods=["POST"])
def open_gate():
    with lock:
        if not ensure_session():
            return jsonify({"success": False, "error": "session failed"}), 503
        return _send_command(turn_on=True)


@app.route("/close", methods=["POST"])
def close_gate():
    with lock:
        if not ensure_session():
            return jsonify({"success": False, "error": "session failed"}), 503
        return _send_command(turn_on=False)


def _upload_log(action: str):
    """Upload a control log entry to mirror what the app does after each command."""
    body = {
        "action":   action,
        "deviceId": session["device_id"],
    }
    result = api_post(
        "/bluetooth/uploadBluetoothControlLog",
        body,
        token=session["token"],
        user_id=session["user_id"],
    )
    log.info("Log upload (%s): %s", action, result)


def _send_set_menu(ble_code: str, cmd_byte: str, step: str) -> dict | None:
    """
    Send a single SET_MENU command.

    Value format (14 hex chars): 3A + bleCode(8) + cmdByte(2) + actionByte(2)
      e.g.  3A 95432482 04 01   (open)
            3A 95432482 04 02   (close)
    """
    value = f"3A{ble_code}{cmd_byte}{step}"
    body = {
        "deviceId":      session["device_id"],
        "propertyValue": {"type": "SET_MENU", "object": {"value": value}},
        "userId":        session["user_id"],
        "action":        "",
    }
    log.info("SET_MENU value=%s", value)
    return api_post("/wifi/sendWifiCode", body, token=session["token"], user_id=session["user_id"])


def _send_command(turn_on: bool):
    """
    Send open/close command for WiFi+BLE Sliding Gate using SET_MENU protocol.

    Confirmed from mitmproxy captures:
      Open:  3A{bleCode}0401 → response 3A{bleCode}01
      Close: 3A{bleCode}0402 → response 3A{bleCode}02

    Both use cmd byte 04. The action byte is 01=open, 02=close.
    bleCode is the 8-char hex identifier in device properties, e.g. "95432482".
    """
    label       = "Open" if turn_on else "Close"
    action_byte = "01" if turn_on else "02"

    ble_code = session.get("ble_code")
    if not ble_code:
        log.error("bleCode not available — cannot build SET_MENU command")
        return jsonify({"success": False, "error": "bleCode not found in device properties"}), 500

    log.info("%s gate: bleCode=%s actionByte=%s", label, ble_code, action_byte)

    data = _send_set_menu(ble_code, "04", action_byte)
    msg  = decode_msg(data.get("msg", "")) if data else "no response"
    log.info("%s response: code=%s msg=%s result=%s",
             label, data.get("code") if data else "none", msg,
             data.get("result") if data else "none")

    if not data or data.get("code") != "0":
        if handle_token_expiry(msg) and ensure_session():
            data = _send_set_menu(ble_code, "04", action_byte)
        if not data or data.get("code") != "0":
            log.error("%s FAILED: %s", label, msg)
            return jsonify({"success": False, "error": f"{label} failed: {msg}"}), 500

    # Upload log to match app behaviour
    _upload_log(label)

    log.info("%s gate command complete", label)
    return jsonify({"success": True})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=PORT)