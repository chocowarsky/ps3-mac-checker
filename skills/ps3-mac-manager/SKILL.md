---
name: ps3-mac-manager
description: >-
  Zero-dependency, 100% offline cross-platform CLI & TUI utility (Windows,
  macOS, Linux) to read, change, pair (sixpair), clone, back up, and manage
  Master and Device Bluetooth MAC addresses on Sony PS3 (DualShock 3 / Sixaxis)
  controllers over USB for ESP32, Arduino, and PC Bluetooth. Use whenever the
  user asks to inspect or reprogram a PS3 controller's Bluetooth MAC address,
  generate ESP32 Ps3.begin() snippets, manage robot MAC profiles, or diagnose
  PS3 USB HID/udev/Bluetooth issues.
license: MIT
metadata:
  author: chocowarsky
  version: "2.0.0"
---

# ps3-mac-manager — Offline PS3 Controller Bluetooth MAC Manager

Zero-dependency Python 3.8+ hardware utility (`ps3_mac_manager.py`) using native OS USB HID backends on Windows (`hid.dll`/`setupapi.dll`), macOS (`IOKit`/`CoreFoundation`), and Linux (`/dev/hidraw*`).

**100% offline — requires zero API keys, zero cloud accounts, and zero pip installs.**

## Non-Negotiable Agent Safety Rules

1. **Always run non-interactively in agent shells:** Pass `-j -n --no-sudo` (`--json --non-interactive --no-sudo`) so the tool NEVER blocks on interactive TUI menus or `sudo` password prompts.
2. **Start with offline read-only diagnostics:** Run `--doctor --json` first to verify OS backend, USB HID driver/`udev` rule status, host Bluetooth adapters, and connected controllers.
3. **Confirm before hardware EEPROM writes:** Never invoke mutating commands (`-s`, `-g`, `-p`, `--apply-profile`, `--clone`, `--restore`) unless the user explicitly asks to reprogram the controller. Never pass `--force` (multicast/broadcast/all-zeros MACs) without explicit confirmation.
4. **No unsolicited `sudo`:** If Linux reports `Permission denied (udev rule required)`, instruct the user to run `./install.sh` once (installs `99-ps3-controller.rules`) or run the command themselves with `sudo`.
5. **Local profile/backup storage only:** Profiles and auto-backups live locally in `~/.config/ps3-mac-manager/config.json` (Linux/macOS) or `%APPDATA%\ps3-mac-manager\config.json` (Windows). No API keys or secrets are used.

## Standard Agent Workflow

Invoke `ps3-mac-manager` if installed on `PATH`, or `python3 ps3_mac_manager.py` directly from the repository root.

### Step 1: Offline Diagnostics & Controller Detection

```bash
python3 ps3_mac_manager.py --doctor --json
```

Read-only check for connected controllers (returns Master MAC, Device MAC, and ready-to-paste `Ps3.begin(...)` + C-array snippets):

```bash
python3 ps3_mac_manager.py --check -j -n -t 0 --no-sudo
```

### Step 2: Common Operations (Only When Requested)

```bash
# Write a specific Master MAC (accepts aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff, raw hex, or C array)
python3 ps3_mac_manager.py -s 00:1d:0d:4c:e3:78 -j -n --no-sudo

# Generate and write a safe locally-administered unicast MAC (for ESP32)
python3 ps3_mac_manager.py -g -j -n --no-sudo

# Pair controller to this computer's local Bluetooth adapter (sixpair mode)
python3 ps3_mac_manager.py -p -j -n --no-sudo

# Named profiles (offline save, apply, list, delete)
python3 ps3_mac_manager.py --save-profile robot1 -s 00:1d:0d:4c:e3:78 -j -n
python3 ps3_mac_manager.py --apply-profile robot1 -j -n --no-sudo
python3 ps3_mac_manager.py --list-profiles -j -n
python3 ps3_mac_manager.py --delete-profile robot1 -j -n

# Backup, restore, and multi-controller clone
python3 ps3_mac_manager.py --backup backup.json -j -n --no-sudo
python3 ps3_mac_manager.py --restore -j -n --no-sudo
python3 ps3_mac_manager.py --clone -a -j -n --no-sudo
```

## Troubleshooting Hints to Relay to Users
- **Controller not detected:** Verify the mini-USB cable is **data-capable** (many charging cables omit data pins).
- **Windows:** Keep the built-in `"HID-compliant game controller"` driver; do NOT replace it with Zadig/WinUSB. Close Steam/ScpToolkit/DsHidMini if exclusive-lock errors occur.
- **macOS:** Grant Terminal access in **System Settings → Privacy & Security → Input Monitoring**.
- **Linux:** Run `./install.sh` once to install `/etc/udev/rules.d/99-ps3-controller.rules` for non-root `/dev/hidraw*` access.
- **After writing a MAC:** Always unplug the USB cable BEFORE pressing the PS button so the controller connects wirelessly.
