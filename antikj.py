#!/usr/bin/env python3
"""
Intrusion Watcher with Local Logging
------------------------------------
Surveille l’activité clavier et souris via evdev.
Quand NumLock est **OFF**, toute activité déclenche :
  - enregistrement des touches dans un fichier log
  - capture webcam (fswebcam)
  - capture d’écran (scrot en JPG)
  - envoi d’alerte Telegram (texte + images)

Fonctionnalités :
  - NumLock agit comme interrupteur ON/OFF
  - Cooldown global : 3 secondes entre deux alertes
  - Fichier log local horodaté
  - La touche NumLock est ignorée pour éviter les faux positifs

Prérequis :
    sudo apt install fswebcam scrot python3-evdev
    pip install requests
Variables d’environnement requises :
    TG_BOT_TOKEN = "<telegram bot token>"
    TG_CHAT_ID   = "<chat id ou group id>"
"""

import os
import time
import subprocess
import requests
from pathlib import Path
from evdev import InputDevice, list_devices, ecodes
from select import select

# =====================
# Config & Telegram
# =====================

TELEGRAM_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise RuntimeError("Environment variables TG_BOT_TOKEN and TG_CHAT_ID are required")

def send_telegram_message(msg: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
        if not r.ok:
            print("Telegram message error:", r.text)
    except Exception as e:
        print("Telegram message error:", e)

def send_telegram_photo(photo_path: str, caption: str = "") -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            mime = "image/jpeg" if photo_path.endswith(".jpg") else "image/png"
            files = {"photo": (os.path.basename(photo_path), f, mime)}
            r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption},
                              files=files, timeout=10)
            if not r.ok:
                print("Telegram photo error:", r.text)
    except Exception as e:
        print("Telegram photo error:", e)

# =====================
# Keymap
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
# Capture & Logging
# =====================

OUTPUT_DIR = Path.home() / "security"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = OUTPUT_DIR / "intrusion_log.txt"

def append_to_log(entry: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {entry}\n")

def take_screenshot() -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"screenshot_{ts}.jpg"
    subprocess.run(["scrot", str(filename)], check=True)
    time.sleep(0.2)
    return filename

def take_webcam_photo(source: str) -> Path:
    filename = OUTPUT_DIR / f"intrusion_{source}_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
    subprocess.run(["fswebcam", str(filename)], check=True)
    time.sleep(0.2)
    return filename

# =====================
# Intrusion Handling
# =====================

last_intrusion_time = 0
typed_buffer = ""

def record_intrusion(source: str, typed_text: str = "") -> None:
    global last_intrusion_time
    now = time.time()
    if now - last_intrusion_time < 3:
        return
    last_intrusion_time = now

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    photo_file = take_webcam_photo(source)
    screenshot_file = take_screenshot()

    caption = f"Intrusion via {source} at {ts}"
    if typed_text:
        caption += f"\nTyped so far: {typed_text}"

    append_to_log(caption)
    send_telegram_message(caption)
    send_telegram_photo(str(photo_file), caption="📷 Webcam")
    send_telegram_photo(str(screenshot_file), caption="🖥️ Screenshot")

# =====================
# Device Detection
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
if numlock_dev:
    devices.append(numlock_dev)
devices.extend(keyboards)
devices.extend(mice)
fds = {dev.fd: dev for dev in devices}

numlock_on = ecodes.LED_NUML in numlock_dev.leds() if numlock_dev else False
surveillance_enabled = not numlock_on  # actif quand NumLock est OFF

print("🎯 Intrusion Watcher running (active when NumLock OFF, cooldown 3s)")

# =====================
# Main Loop
# =====================

while True:
    r, _, _ = select(fds, [], [])
    for fd in r:
        dev = fds[fd]
        for event in dev.read():
            if dev == numlock_dev and event.type == ecodes.EV_LED and event.code == ecodes.LED_NUML:
                numlock_on = bool(event.value)
                print("NumLock =", "ON" if numlock_on else "OFF")
                surveillance_enabled = not numlock_on
                if not surveillance_enabled:
                    typed_buffer = ""
                continue

            if surveillance_enabled:
                if dev in keyboards and event.type == ecodes.EV_KEY and event.value == 1:
                    if event.code == ecodes.KEY_NUMLOCK:
                        continue  # ignorer la touche NumLock
                    char = KEYMAP.get(event.code, f"[{event.code}]")
                    typed_buffer += char
                    append_to_log(f"Key pressed: {char}")
                    record_intrusion("keyboard", typed_buffer)

                elif dev in mice:
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        append_to_log("Mouse click detected")
                        record_intrusion("mouse_click", typed_buffer)
                    elif event.type == ecodes.EV_REL:
                        append_to_log("Mouse movement detected")
                        record_intrusion("mouse_move", typed_buffer)
