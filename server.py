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
API_BASE_URL  = "http://47.52.111.184:9010/xhouseAppEncapsulation"
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
        "host":         "47.52.111.184:9010",
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
        {"userId": int(session["user_id"]), "groupId": 0},
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
            session["device_id"] = int(device["id"])
            session["device"]    = device
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
        "device":    (session["device"].get("alias") or session["device"].get("model")) if session.get("device") else None,
    })


@app.route("/status", methods=["GET"])
def status():
    with lock:
        if not ensure_session():
            return jsonify({"state": "unknown", "error": "session failed"}), 503

        data = api_post(
            "/wifi/getWifiProperties",
            {"userId": int(session["user_id"]), "deviceId": session["device_id"]},
            token=session["token"],
            user_id=session["user_id"],
        )

        if not data or data.get("code") != "0":
            msg = decode_msg(data.get("msg", "")) if data else "no response"
            handle_token_expiry(msg)
            return jsonify({"state": "unknown", "error": msg}), 503

        is_on = False
        for prop in data.get("result", {}).get("properties", []):
            if prop.get("key") == "Switch_1":
                is_on = prop.get("value") == "1"
                break

        state = "open" if is_on else "closed"
        log.info("Status: %s", state)
        return jsonify({"state": state})


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


def _send_command(turn_on: bool):
    """Send open/close command using exact same format as original gist."""
    body = {
        "deviceId":      int(session["device_id"]),
        "userId":        int(session["user_id"]),
        "propertyValue": {"Switch_1": 1 if turn_on else 0},
        "action":        "On" if turn_on else "Off",  # API always uses On/Off per original gist
    }
    log.info("Sending command: %s", body)
    data = api_post("/wifi/sendWifiCode", body, token=session["token"], user_id=session["user_id"])

    msg = decode_msg(data.get("msg", "")) if data else "no response"
    log.info("Command response: code=%s msg=%s", data.get("code") if data else "none", msg)

    if data and data.get("code") == "0":
        log.info("Gate command SUCCESS")
        return jsonify({"success": True})

    # Token expired — re-login and retry once
    if handle_token_expiry(msg):
        if ensure_session():
            data = api_post("/wifi/sendWifiCode", body, token=session["token"], user_id=session["user_id"])
            if data and data.get("code") == "0":
                log.info("Gate command SUCCESS after re-login")
                return jsonify({"success": True})
            msg = decode_msg(data.get("msg", "")) if data else "no response"

    log.error("Gate command FAILED: %s", msg)
    return jsonify({"success": False, "error": msg}), 500


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=PORT)