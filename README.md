# PS3 Controller MAC Address Manager

[![Release](https://img.shields.io/github/v/release/chocowarsky/ps3-mac-manager)](https://github.com/chocowarsky/ps3-mac-manager/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, **zero-dependency** cross-platform tool for **Windows (10/11)**, **macOS**, and **Linux (Ubuntu, Fedora, Debian, Arch)** to **read, change, pair, clone, back up, and manage** both the **Master MAC address** and **Device MAC address** on Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers over USB.

Built for **ESP32 / Arduino** makers using [`esp32-ps3`](https://github.com/jvpernis/esp32-ps3) / `Ps3Controller.h`, robotics teams swapping spare controllers without reflashing ESP32 firmware, and Windows/macOS/Linux users pairing PS3 controllers via Bluetooth (`sixpair` replacement).

---

## 1-Command Quickstart (For Beginners)

Plug your PS3 controller into your computer with a **data-capable mini-USB cable**, then run **one command** for your operating system:

### Windows 10 / 11 (PowerShell — Recommended)
Open **PowerShell** (press `Win + X` → **Terminal** / **PowerShell**) and run:
```powershell
irm https://raw.githubusercontent.com/chocowarsky/ps3-mac-manager/main/install.ps1 | iex
```
This automatically checks/installs Python if needed, installs `ps3-mac-manager`, adds a **Desktop shortcut**, and opens the tool right away.

> **Prefer downloading manually?** Download/clone this repo and double-click **`ps3_mac_manager.bat`**.

---

### macOS (Intel & Apple Silicon)
Open **Terminal** and run:
```bash
curl -fsSL https://raw.githubusercontent.com/chocowarsky/ps3-mac-manager/main/install.sh | bash
```
Then run **`ps3-mac-manager`** in Terminal (or double-click **`PS3_MAC_Manager.command`** on your Desktop).

---

### Linux (Ubuntu, Fedora, Debian, Arch, Mint)
Open **Terminal** and run:
```bash
curl -fsSL https://raw.githubusercontent.com/chocowarsky/ps3-mac-manager/main/install.sh | bash
```
This installs the `ps3-mac-manager` command, sets up the non-root `udev` rule (`99-ps3-controller.rules`), and adds **PS3 MAC Manager** to your application menu. Then launch it from your app menu or run:
```bash
ps3-mac-manager
```

> **Install via `pip` / `pipx` / `uv` (Optional):**
> ```bash
> pipx install git+https://github.com/chocowarsky/ps3-mac-manager.git
> ```
> *(On Linux, also copy `99-ps3-controller.rules` to `/etc/udev/rules.d/` or run with `sudo` if not using `install.sh`.)*

---

## Why Manage the Master MAC?

PS3 controllers store two Bluetooth MAC addresses:

1. **Master MAC (Host Address):** The Bluetooth address the controller actively searches for when you press the **PS button**.
   - **Check mode:** Extract the controller's existing Master MAC to paste into `Ps3.begin("00:1d:0d:4c:e3:78");`.
   - **Write / Manage mode:** Reprogram the controller's Master MAC over USB to match your **ESP32**, your **PC's Bluetooth adapter**, a **saved robot profile**, or a **newly generated unicast MAC**.
2. **Device MAC (Controller Address):** The controller's own physical Bluetooth MAC address.

### Real-World Example: Swapping Spare Controllers Without Reflashing
Suppose your robot's ESP32 already runs `Ps3.begin("00:1d:0d:4c:e3:78");`, and your primary DualShock 3 battery dies mid-match:
1. Plug in any spare PS3 controller via mini-USB.
2. Run `ps3-mac-manager -s 00:1d:0d:4c:e3:78` (or `--apply-profile robot1`).
3. Unplug and press the **PS button** — it connects directly to your ESP32 without touching Arduino code.

---

## Features

- **Cross-Platform Zero-Dependency Core:** Pure Python 3.8+ standard library on **Windows (`hid.dll` / `setupapi.dll` / `bthprops.cpl`)**, **macOS (`IOKit` / `CoreFoundation`)**, and **Linux (`/dev/hidraw*` / `sysfs`)**. No `pip install` or Zadig drivers required.
- **Read & Write Master MAC (with Read-Back Verification):** Reads Feature Report `0xF5` and writes new Master MAC addresses, then immediately reads back to confirm EEPROM persistence.
- **Interactive TUI Dashboard:** Launch with no flags to inspect connected controllers, view copy-paste `Ps3.begin(...)` + C array snippets, change MACs, apply profiles, pair to host Bluetooth, restore backups, or run diagnostics.
- **Built-in Diagnostics (`--doctor`):** Instantly checks OS backend, Python runtime, USB HID drivers / `udev` rules, host Bluetooth adapters, and troubleshooting tips.
- **One-Click Host Bluetooth Pairing (`--pair-host`):** Automatically detects local Bluetooth adapters on Windows, macOS, and Linux and pairs the controller directly (`sixpair` replacement).
- **Named Profiles (`--save-profile` / `--apply-profile`):** Save robot/controller MAC presets in `~/.config/ps3-mac-manager/config.json` (or `%APPDATA%\ps3-mac-manager\config.json` on Windows).
- **Automatic Backup & Restore (`--restore` / `--backup`):** Automatically backs up the controller's previous Master MAC before every write, and supports standalone JSON backup export/restore inside the working directory.
- **Safe Random MAC Generator (`--generate-mac`):** Generates locally administered unicast MAC addresses (never multicast, all-zeros, or `ff:ff:ff:ff:ff:ff`).
- **Multi-Controller Cloning (`--clone`):** Copy Controller #1's Master MAC across multiple plugged-in controllers.
- **Flexible Input & Clone Resilience:** Accepts `aa:bb:cc:dd:ee:ff`, `aa-bb-cc-dd-ee-ff`, `aabb.ccdd.eeff`, raw hex, or pasted C-array bytes (`{0x00, 0x1d, ...}`), and supports both 8-byte canonical and 64/65-byte padded HID feature reports.

---

## Usage

### 1. Interactive TUI / Desktop Launcher
- **Windows:** Run **`ps3-mac-manager`** in PowerShell/CMD, or double-click **`PS3 MAC Manager`** on your Desktop (or **`ps3_mac_manager.bat`**).
- **macOS:** Run **`ps3-mac-manager`** in Terminal, or double-click **`PS3_MAC_Manager.command`** on your Desktop.
- **Linux:** Launch **PS3 MAC Manager** from your application menu, run **`ps3-mac-manager`**, or run `./ps3_mac_manager.sh`.

### 2. Command Line Reference
```bash
# Interactive management dashboard
ps3-mac-manager

# Check system setup, drivers, udev rules & Bluetooth adapters
ps3-mac-manager --doctor

# Read-only check
ps3-mac-manager --check
ps3-mac-manager -j -n -t 5               # Non-interactive JSON output

# Change Master MAC (accepts aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff, raw hex, or C array)
ps3-mac-manager -s 00:1d:0d:4c:e3:78
ps3-mac-manager -g                       # Generate & write random safe unicast MAC

# Pair controller to this computer's Bluetooth adapter (sixpair mode)
ps3-mac-manager -p
ps3-mac-manager -p --adapter hci0        # Choose specific adapter

# Manage named profiles
ps3-mac-manager --save-profile robot1    # Save connected controller's Master MAC
ps3-mac-manager --save-profile robot1 -s 00:1d:0d:4c:e3:78  # Save offline
ps3-mac-manager --apply-profile robot1   # Write 'robot1' MAC to controller
ps3-mac-manager --list-profiles          # List saved profiles & backups
ps3-mac-manager --delete-profile robot1  # Delete a saved profile

# Backup, Restore & Multi-Controller Clone
ps3-mac-manager --restore                # Restore previous MAC from auto-backup
ps3-mac-manager --backup backup.json     # Export controller state to JSON file
ps3-mac-manager --restore backup.json    # Restore from exported JSON file
ps3-mac-manager --clone -a               # Copy Controller #1's MAC to all others
```

*(If running straight from a cloned repo without installing, replace `ps3-mac-manager` with `python3 ps3_mac_manager.py` on Linux/macOS or `python ps3_mac_manager.py` on Windows.)*

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
  [7] System diagnostics & troubleshooting (--doctor)
  [Enter / Q] Exit
```

---

## Troubleshooting

- **Controller not detected?** Make sure your mini-USB cable supports **data transfer** (many charging-only cables lack USB data wires). Run `ps3-mac-manager --doctor` to verify drivers and permissions.
- **Windows:** Keep the built-in Windows **"HID-compliant game controller"** driver — do **not** replace it with Zadig/WinUSB. If Steam, ScpToolkit, or DsHidMini has an exclusive lock, close them before writing.
- **macOS:** If opening the controller fails with a permission error, allow Terminal in **System Settings → Privacy & Security → Input Monitoring**.
- **Linux (Ubuntu / Fedora / Debian / Arch):** Run `install.sh` so `99-ps3-controller.rules` grants non-root `/dev/hidraw*` access, or run with `sudo`.

---

## Technical Details

- **Windows (`win32`):** Uses Win32 APIs via `setupapi.dll` (`SetupDiGetClassDevsW`), `kernel32.dll` (`CreateFileW` with read/write and metadata-sharing fallback), `hid.dll` (`HidD_GetFeature` / `HidD_SetFeature` across 8/64/65-byte reports for `0xF5` & `0xF2`), and `bthprops.cpl` (`BluetoothFindFirstRadio` / `BluetoothGetRadioInfo`).
- **macOS (`darwin`):** Uses `IOKit.framework` (`IOHIDManagerCreate`, `IOHIDDeviceGetReport` / `IOHIDDeviceSetReport` for `0xF5` & `0xF2`) and `CoreFoundation.framework` via `ctypes`, plus `system_profiler SPBluetoothDataType` / `ioreg` for host Bluetooth discovery.
- **Linux (`linux`):** Exposes HID devices via `/dev/hidraw*` using `HIDIOCGFEATURE` / `HIDIOCSFEATURE` on `0xF5` and reads Device MAC from sysfs `HID_UNIQ`, `input*/uniq`, or `0xF2`. Host Bluetooth adapters are read from `/sys/class/bluetooth/hci*/address`.

---

## AI Agent Harness Support

`ps3-mac-manager` ships native instructions and manifests for every major AI agent harness (**Antigravity, Claude Code, Codex, Cursor, Windsurf, VS Code / Copilot, OpenCode, Cline, Roo Code**):

```bash
# Install as an Agent Skill via skills.sh CLI
npx skills add chocowarsky/ps3-mac-manager
```

- **100% offline & zero API keys required.** Local profiles/backups live in `~/.config/ps3-mac-manager/config.json`.
- **Non-interactive agent rule:** Always pass `-j -n --no-sudo` (`python3 ps3_mac_manager.py --doctor --json`, `--check -j -n -t 0 --no-sudo`).
- See [`AGENTS.md`](AGENTS.md) and [`skills/ps3-mac-manager/SKILL.md`](skills/ps3-mac-manager/SKILL.md) for full agent instructions.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
