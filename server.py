#!/usr/bin/env python3
"""
X-House IOT Gate Server
A tiny persistent Flask server that keeps a session with the X-House API
and exposes simple HTTP endpoints for Home Assistant to call.

Endpoints:
  GET  /status   -> returns {"state": "open"} or {"state": "closed"}
  POST /open     -> opens the gate
  POST /close    -> closes the gate
  GET  /health   -> returns {"status": "ok"}
"""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
import urllib.error
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

GATE_KEYWORDS   = ["gate", "xh-sgc01", "sgc01", "sliding", "swing", "barrier", "wifi+ble"]
GARAGE_KEYWORDS = ["garage", "door"]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
lock = Lock()  # Thread safety for session state

# ── Session state ─────────────────────────────────────────────────────────────
session = {
    "token":     None,
    "user_id":   None,
    "device_id": None,
}


# ── API helpers ───────────────────────────────────────────────────────────────

def signed_headers(token=None, user_id=None):
    timestamp    = str(int(time.time()))
    data_to_sign = PLATFORM_CODE + timestamp
    signature    = hmac.new(
        HMAC_SECRET.encode("utf-8"),
        data_to_sign.encode("utf-8"),
        hashlib.md5,
    ).hexdigest()
    headers = {
        "apptype":        APP_TYPE,
        "l":              "EN",
        "phonetime":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platformcode":   PLATFORM_CODE,
        "saascode":       SAAS_CODE,
        "timestamp":      timestamp,
        "signature":      signature,
        "Content-Type":   "application/json; charset=utf-8",
        "User-Agent":     "okhttp/4.2.0",
        "Host":           "47.52.111.184:9010",
        "Connection":     "Keep-Alive",
    }
    if token:
        headers["token"]  = token
        headers["userid"] = str(user_id)
    return headers


def api_post(path, body, token=None, user_id=None):
    body_str = json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers  = signed_headers(token, user_id)
    headers["content-length"] = str(len(body_str))
    req = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=body_str,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.error("API error on %s: %s", path, e)
        return None


# ── Auth & discovery ──────────────────────────────────────────────────────────

def do_login():
    """Login and store token + user_id in session. Returns True on success."""
    log.info("Logging in as %s...", EMAIL)
    body_str = json.dumps(
        {
            "saasCode": SAAS_CODE,
            "type":     "EMAIL",
            "email":    EMAIL,
            "password": PASSWORD,
            "appType":  APP_TYPE.upper(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = signed_headers()
    headers["content-length"] = str(len(body_str))
    req = urllib.request.Request(
        f"{API_BASE_URL}/clientUser/login",
        data=body_str,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.error("Login failed: %s", e)
        return False

    if data.get("code") == "0":
        session["token"]   = data["result"]["token"]
        session["user_id"] = data["result"]["userId"]
        log.info("Login successful. User ID: %s", session["user_id"])
        return True

    log.error("Login error: %s", data.get("msg"))
    return False


def discover_device():
    """Find the gate device and store its ID in session. Returns True on success."""
    data = api_post(
        "/group/queryGroupDevices",
        {"userId": int(session["user_id"]), "groupId": 0},
        token=session["token"],
        user_id=session["user_id"],
    )
    if not data or data.get("code") != "0":
        log.error("Device discovery failed: %s", data.get("msg") if data else "no response")
        return False

    devices = data.get("result", {}).get("deviceInfos", [])
    for device in devices:
        model = (device.get("model") or "").lower()
        alias = (device.get("alias") or "").lower()
        if any(k in model or k in alias for k in GATE_KEYWORDS + GARAGE_KEYWORDS):
            session["device_id"] = int(device["id"])
            log.info("Found gate device: %s (id=%s)", device.get("alias") or device.get("model"), session["device_id"])
            return True

    log.error("No gate device found. Devices: %s", [d.get("alias") or d.get("model") for d in devices])
    return False


def ensure_session():
    """Ensure we have a valid token and device ID, re-login if needed."""
    if not session["token"]:
        if not do_login():
            return False
    if not session["device_id"]:
        if not discover_device():
            return False
    return True


def handle_token_expiry(msg):
    """If token expired, clear it so next call triggers re-login."""
    if msg and "token invalid" in msg.lower():
        log.warning("Token expired, will re-login on next request")
        session["token"] = None
        return True
    return False


# ── Startup ───────────────────────────────────────────────────────────────────

def startup():
    """Login and discover device on startup."""
    if not EMAIL or not PASSWORD:
        log.error("XHOUSE_EMAIL and XHOUSE_PASSWORD environment variables must be set!")
        return
    with lock:
        do_login()
        if session["token"]:
            discover_device()


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "device_id": session.get("device_id")})


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
            msg = data.get("msg", "") if data else ""
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

        data = api_post(
            "/wifi/sendWifiCode",
            {
                "deviceId":      session["device_id"],
                "userId":        int(session["user_id"]),
                "propertyValue": {"Switch_1": 1},
                "action":        "Open",
            },
            token=session["token"],
            user_id=session["user_id"],
        )

        if data and data.get("code") == "0":
            log.info("Gate opened successfully")
            return jsonify({"success": True})

        msg = data.get("msg", "") if data else "no response"
        handle_token_expiry(msg)
        # Re-try once after re-login
        if not session["token"]:
            ensure_session()
            data = api_post(
                "/wifi/sendWifiCode",
                {
                    "deviceId":      session["device_id"],
                    "userId":        int(session["user_id"]),
                    "propertyValue": {"Switch_1": 1},
                    "action":        "Open",
                },
                token=session["token"],
                user_id=session["user_id"],
            )
            if data and data.get("code") == "0":
                log.info("Gate opened successfully (after re-login)")
                return jsonify({"success": True})

        log.error("Open failed: %s", msg)
        return jsonify({"success": False, "error": msg}), 500


@app.route("/close", methods=["POST"])
def close_gate():
    with lock:
        if not ensure_session():
            return jsonify({"success": False, "error": "session failed"}), 503

        data = api_post(
            "/wifi/sendWifiCode",
            {
                "deviceId":      session["device_id"],
                "userId":        int(session["user_id"]),
                "propertyValue": {"Switch_1": 0},
                "action":        "Close",
            },
            token=session["token"],
            user_id=session["user_id"],
        )

        if data and data.get("code") == "0":
            log.info("Gate closed successfully")
            return jsonify({"success": True})

        msg = data.get("msg", "") if data else "no response"
        handle_token_expiry(msg)
        # Re-try once after re-login
        if not session["token"]:
            ensure_session()
            data = api_post(
                "/wifi/sendWifiCode",
                {
                    "deviceId":      session["device_id"],
                    "userId":        int(session["user_id"]),
                    "propertyValue": {"Switch_1": 0},
                    "action":        "Close",
                },
                token=session["token"],
                user_id=session["user_id"],
            )
            if data and data.get("code") == "0":
                log.info("Gate closed successfully (after re-login)")
                return jsonify({"success": True})

        log.error("Close failed: %s", msg)
        return jsonify({"success": False, "error": msg}), 500


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=PORT)
