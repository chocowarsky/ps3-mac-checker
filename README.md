# PS3 Controller MAC Address Checker

[![Release](https://img.shields.io/github/v/release/chocowarsky/ps3-mac-checker)](https://github.com/chocowarsky/ps3-mac-checker/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, zero-dependency cross-platform tool (Linux & Windows) to extract both the **Master MAC address** and **Device MAC address** from Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers over USB.

Designed specifically for makers building robotics, RC cars, and IoT projects using **ESP32** and the [`ESP32-PS3`](https://github.com/jvpernis/esp32-ps3) Arduino library.

---

## Why Two MAC Addresses?

When connecting a PS3 controller wirelessly to an ESP32, many users run into connection failures because PS3 controllers store two different MAC addresses:

1. **Master MAC (Host Address):** The Bluetooth address of the console/host the controller was paired to. When you press the circular **PS button**, the controller actively searches for this master address. To connect, your ESP32 must mimic this address using:
   ```cpp
   Ps3.begin("00:1d:0d:4c:e3:78"); // Put the Master MAC here!
   ```
2. **Device MAC (Controller Address):** The controller's own physical Bluetooth MAC address. Putting this address in `Ps3.begin()` will **not** work because the controller does not listen for incoming connections.

This tool extracts both addresses and formats the exact line ready to copy into your Arduino sketch.

---

## Features

- **Cross-Platform (Linux & Windows):** Runs seamlessly on Ubuntu / Debian / Fedora / Arch Linux and Windows 10 / 11.
- **Zero external dependencies:** Pure Python standard library only (`ctypes`, `fcntl`, `glob`, `os`, `sys`). No `pip install` required.
- **Live connection polling:** If the controller is not plugged in yet, the script waits until you connect the mini-USB cable.
- **Double-click desktop launcher:** Includes an XDG `.desktop` launcher with terminal auto-spawn for Linux (Ubuntu / GNOME) and `ps3_mac_checker.bat` for Windows.
- **Terminal stays open:** Prompts before exit so you have plenty of time to copy the MAC address.
- **Non-root / Standard user:** Includes a Linux udev rule; on Windows uses standard user-mode Win32 HID APIs (no Administrator elevation needed).

---

## Installation & Quickstart

### On Linux (Ubuntu / Debian / Fedora / Arch)
Clone the repository and run the installer:
```bash
git clone https://github.com/chocowarsky/ps3-mac-checker.git
cd ps3-mac-checker
chmod +x install.sh
./install.sh
```

### On Windows (10 / 11)
1. Install Python 3.10+ from [python.org](https://www.python.org/) (make sure to check **"Add Python to PATH"**).
2. Clone or download the repository:
   ```cmd
   git clone https://github.com/chocowarsky/ps3-mac-checker.git
   cd ps3-mac-checker
   ```
3. Connect your PS3 controller via mini-USB.
4. Double-click **`ps3_mac_checker.bat`** in File Explorer (or run `python ps3_mac_checker.py` in Command Prompt / PowerShell).

---

## Usage

### 1. GUI / Desktop Launcher
- **Linux:** Open application menu (press `Super`) and search for **PS3 MAC Checker**, or double-click `Check_PS3_MAC.desktop` in `~/Arduino`.
- **Windows:** Double-click **`ps3_mac_checker.bat`** in the project folder.

### 2. Command Line
Run directly in your terminal:
```bash
# On Linux:
./ps3_mac_checker.sh
# or:
python3 ps3_mac_checker.py

# On Windows:
ps3_mac_checker.bat
# or:
python ps3_mac_checker.py
```

#### Advanced CLI Options
```bash
python3 ps3_mac_checker.py --help
python3 ps3_mac_checker.py -j                    # Machine-readable JSON output
python3 ps3_mac_checker.py -n -t 5               # Non-interactive with 5-second timeout
python3 ps3_mac_checker.py --all                 # Enumerate all connected PS3 controllers
python3 ps3_mac_checker.py --no-sudo             # Disable automatic sudo re-elevation
```

### Example Output

```text
============================================================
           PS3 CONTROLLER MAC ADDRESS CHECKER               
============================================================

[✓] PS3 Controller detected!

------------------------------------------------------------
1. MASTER MAC (Required for ESP32 / Ps3.begin):
   >>  00:1d:0d:4c:e3:78  <<

   Paste this into setup() in your Arduino IDE:
   Ps3.begin("00:1d:0d:4c:e3:78");
------------------------------------------------------------
2. DEVICE MAC (Physical Bluetooth Address of Controller):
   >>  a0:5a:5e:9b:aa:08  <<
------------------------------------------------------------

Done! Press [Enter] to close terminal...
```

---

## Technical Details

- **Linux:** Exposes HID devices via `/dev/hidraw*`. Uses `ioctl(fd, HIDIOCGFEAT, buf)` with Feature Report `0xF5` (Master bdaddr) and reads `HID_UNIQ` from sysfs `uevent` (Device bdaddr).
- **Windows:** Uses Win32 Device Management APIs via `setupapi.dll` (`SetupDiGetClassDevsW` for HID class GUID) to find `VID_054C&PID_0268` interfaces. Opens the interface via `kernel32.dll` (`CreateFileW`) and reads Feature Report `0xF5` (Master bdaddr) and Feature Report `0xF2` (Device bdaddr) via `hid.dll` (`HidD_GetFeature`). No external drivers (e.g. Zadig/ScpToolkit) required.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
