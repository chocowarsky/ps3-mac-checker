---
name: ps3-mac-manager
description: >-
  Zero-dependency, 100% offline cross-platform CLI & TUI utility (Windows,
  macOS, Linux) to read, change, pair (sixpair), clone, back up, and manage
  Master and Device Bluetooth MAC addresses on Sony PS3 (DualShock 3 / Sixaxis)
  controllers over USB for ESP32, Arduino, and PC Bluetooth.
license: MIT
metadata:
  author: chocowarsky
  version: "2.0.0"
---

# ps3-mac-manager (Repository Root Skill Pointer)

The canonical skill specification lives at [skills/ps3-mac-manager/SKILL.md](skills/ps3-mac-manager/SKILL.md), and universal agent instructions live at [AGENTS.md](AGENTS.md).

## Quick Non-Interactive Agent Commands

```bash
# 1. Offline system, HID driver, udev & Bluetooth diagnostics
python3 ps3_mac_manager.py --doctor --json

# 2. Non-interactive read-only controller check
python3 ps3_mac_manager.py --check -j -n -t 0 --no-sudo
```

Always pass `-j -n --no-sudo` from non-interactive agent shells and never write to controller EEPROM (`-s`, `-g`, `-p`, `--apply-profile`, `--clone`, `--restore`) without explicit user confirmation.
