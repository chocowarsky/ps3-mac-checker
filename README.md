# PS3 Controller MAC Address Manager

[![Release](https://img.shields.io/github/v/release/chocowarsky/ps3-mac-manager)](https://github.com/chocowarsky/ps3-mac-manager/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, zero-dependency cross-platform tool (Linux & Windows) to **read, change, pair, clone, back up, and manage** both the **Master MAC address** and **Device MAC address** on Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers over USB.

Built for **ESP32 / Arduino** makers using [`esp32-ps3`](https://github.com/jvpernis/esp32-ps3) / `Ps3Controller.h`, robotics teams swapping spare controllers without reflashing ESP32 firmware, and Linux/Windows users pairing PS3 controllers via Bluetooth (`sixpair` replacement).

---

## Why Manage the Master MAC?

PS3 controllers store two Bluetooth MAC addresses:

1. **Master MAC (Host Address):** The Bluetooth address the controller actively searches for when you press the **PS button**.
   - **Check mode:** Extract the controller's existing Master MAC to paste into `Ps3.begin("00:1d:0d:4c:e3:78");`.
   - **Write / Manage mode (New in v2.0.0):** Reprogram the controller's Master MAC over USB to match your **ESP32**, your **PC's Bluetooth adapter**, a **saved robot profile**, or a **newly generated unicast MAC**.
2. **Device MAC (Controller Address):** The controller's own physical Bluetooth MAC address (read via sysfs / Feature Report `0xF2`).

### Real-World Example: Swapping Spare Controllers Without Reflashing
Suppose your robot's ESP32 already runs `Ps3.begin("00:1d:0d:4c:e3:78");`, and your primary DualShock 3 battery dies mid-match:
1. Plug in any spare PS3 controller via mini-USB.
2. Run `python3 ps3_mac_manager.py -s 00:1d:0d:4c:e3:78` (or `--apply-profile robot1`).
3. Unplug and press the **PS button** — it connects directly to your ESP32 without touching Arduino code.

---

## Features

- **Read & Write Master MAC (with Read-Back Verification):** Reads Feature Report `0xF5` and writes new Master MAC addresses via `HIDIOCSFEATURE` (Linux) / `HidD_SetFeature` (Windows), then immediately reads back to confirm EEPROM persistence.
- **Interactive TUI Dashboard:** Launch with no flags to inspect connected controllers, view copy-paste `Ps3.begin(...)` + C array snippets, change MACs, apply profiles, pair to host Bluetooth, or restore backups.
- **One-Click Host Bluetooth Pairing (`--pair-host`):** Automatically detects local Bluetooth adapters (`/sys/class/bluetooth/hci*` on Linux, `bthprops.cpl` on Windows) and pairs the controller directly (`sixpair` replacement).
- **Named Profiles (`--save-profile` / `--apply-profile`):** Save robot/controller MAC presets in `~/.config/ps3-mac-manager/config.json` (or `%APPDATA%\ps3-mac-manager\config.json` on Windows) for instant switching.
- **Automatic Backup & Restore (`--restore` / `--backup`):** Automatically backs up the controller's previous Master MAC before every write, and supports standalone JSON backup export/restore.
- **Safe Random MAC Generator (`--generate-mac`):** Generates locally administered unicast MAC addresses (never multicast, all-zeros, or `ff:ff:ff:ff:ff:ff`).
- **Multi-Controller Cloning (`--clone`):** Copy Controller #1's Master MAC across multiple plugged-in controllers.
- **Zero External Dependencies:** Pure Python standard library only (`argparse`, `ctypes`, `fcntl`, `glob`, `json`, `os`, `sys`). No `pip install` or Zadig drivers required.
- **Clone Controller Resilience:** Supports both 8-byte canonical and 64-byte padded HID feature reports, plus validation warnings for unprogrammed clone EEPROMs.

---

## Installation & Quickstart

### On Linux (Ubuntu / Debian / Fedora / Arch)
```bash
git clone https://github.com/chocowarsky/ps3-mac-manager.git
cd ps3-mac-manager
chmod +x install.sh
./install.sh
```

### On Windows (10 / 11)
1. Install Python 3.10+ from [python.org](https://www.python.org/) (check **"Add Python to PATH"**).
2. Clone or download the repository:
   ```cmd
   git clone https://github.com/chocowarsky/ps3-mac-manager.git
   cd ps3-mac-manager
   ```
3. Connect your PS3 controller via mini-USB.
4. Double-click **`ps3_mac_manager.bat`** (or run `python ps3_mac_manager.py` in Command Prompt / PowerShell).

---

## Usage

### 1. Interactive TUI / Desktop Launcher
- **Linux:** Launch **PS3 MAC Manager** from your application menu (`Super`), run `./ps3_mac_manager.sh`, or double-click `PS3_MAC_Manager.desktop` in `~/Arduino`.
- **Windows:** Double-click **`ps3_mac_manager.bat`**.

### 2. Command Line Reference
```bash
# Interactive management dashboard
python3 ps3_mac_manager.py

# Read-only check (legacy ps3-mac-checker behavior)
python3 ps3_mac_manager.py --check
python3 ps3_mac_manager.py -j -n -t 5               # Non-interactive JSON output

# Change Master MAC (accepts aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff, or raw hex)
python3 ps3_mac_manager.py -s 00:1d:0d:4c:e3:78
python3 ps3_mac_manager.py -g                       # Generate & write random safe unicast MAC

# Pair controller to this computer's Bluetooth adapter (sixpair mode)
python3 ps3_mac_manager.py -p
python3 ps3_mac_manager.py -p --adapter hci0        # Choose specific adapter

# Manage named profiles
python3 ps3_mac_manager.py --save-profile robot1    # Save connected controller's Master MAC
python3 ps3_mac_manager.py --save-profile robot1 -s 00:1d:0d:4c:e3:78  # Save offline
python3 ps3_mac_manager.py --apply-profile robot1   # Write 'robot1' MAC to controller
python3 ps3_mac_manager.py --list-profiles          # List saved profiles & backups
python3 ps3_mac_manager.py --delete-profile robot1  # Delete a saved profile

# Backup, Restore & Multi-Controller Clone
python3 ps3_mac_manager.py --restore                # Restore previous MAC from auto-backup
python3 ps3_mac_manager.py --backup backup.json     # Export controller state to JSON file
python3 ps3_mac_manager.py --restore backup.json    # Restore from exported JSON file
python3 ps3_mac_manager.py --clone -a               # Copy Controller #1's MAC to all others
```

### Example Interactive Output

```text
============================================================
         PS3 CONTROLLER MAC ADDRESS MANAGER v2.0.0         
============================================================

[✓] Detected 1 PS3 Controller(s)!

--- CONTROLLER DETAILS --------------------------------------
Hardware Path : /sys/bus/hid/devices/0003:054C:0268.0001
Device Node   : /dev/hidraw0

1. MASTER MAC (Required for ESP32 / Ps3.begin):
   >>  00:1d:0d:4c:e3:78  <<

   Paste into Arduino setup() / C code:
   Ps3.begin("00:1d:0d:4c:e3:78");
   uint8_t master_mac[6] = {0x00, 0x1d, 0x0d, 0x4c, 0xe3, 0x78};

2. DEVICE MAC (Physical Bluetooth Address of Controller):
   >>  a0:5a:5e:9b:aa:08  <<
------------------------------------------------------------

Actions:
  [1] Change Master MAC address (custom)
  [2] Profiles (save / apply / delete presets)
  [3] Generate & write random safe MAC (for ESP32)
  [4] Pair to this PC's Bluetooth adapter (sixpair)
  [5] Restore previous Master MAC from backup
  [6] Refresh / Re-scan controller
  [Enter / Q] Exit
```

---

## Technical Details

- **Linux:** Exposes HID devices via `/dev/hidraw*`. Uses `ioctl(fd, HIDIOCGFEATURE, buf)` and `ioctl(fd, HIDIOCSFEATURE, buf)` on Feature Report `0xF5` (`[0xF5, 0x01, mac0..mac5]`) to read and write the Master Bluetooth MAC, and reads Device MAC from sysfs `HID_UNIQ`, `input*/uniq`, or Feature Report `0xF2`. Local Bluetooth adapters are discovered from `/sys/class/bluetooth/hci*/address`.
- **Windows:** Uses Win32 Device Management APIs via `setupapi.dll` (`SetupDiGetClassDevsW`) to enumerate `VID_054C&PID_0268` interfaces, `kernel32.dll` (`CreateFileW`) for read/write handles, `hid.dll` (`HidD_GetFeature` / `HidD_SetFeature`) for Feature Reports `0xF5` and `0xF2`, and `bthprops.cpl` (`BluetoothFindFirstRadio` / `BluetoothGetRadioInfo`) for host adapter discovery.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
