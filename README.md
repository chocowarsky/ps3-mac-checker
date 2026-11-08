# PS3 Controller MAC Address Checker

[![CI](https://github.com/chocowarsky/ps3-mac-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/chocowarsky/ps3-mac-checker/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/chocowarsky/ps3-mac-checker)](https://github.com/chocowarsky/ps3-mac-checker/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, zero-dependency Linux tool to extract both the **Master MAC address** and **Device MAC address** from Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers over USB.

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

- **No compilation needed:** Written in clean, pure Python 3 using standard library modules (`fcntl`, `glob`, `os`).
- **Live connection polling:** If the controller is not plugged in yet, the script waits until you connect the mini-USB cable.
- **Double-click desktop launcher:** Includes an XDG `.desktop` launcher with terminal auto-spawn for GNOME / Ubuntu.
- **Terminal stays open:** Prompts before exit so you have plenty of time to copy the MAC address.
- **Non-root udev rule:** Includes a udev rule so you don't have to enter a `sudo` password every time.

---

## Installation

Clone the repository and run the installer:

```bash
git clone https://github.com/chocowarsky/ps3-mac-checker.git
cd ps3-mac-checker
chmod +x install.sh
./install.sh
```

The installer will:
1. Place `/etc/udev/rules.d/99-ps3-controller.rules` and reload udev.
2. Install the desktop launcher into `~/.local/share/applications/` and `~/Arduino/`.

---

## Usage

### 1. GUI / Desktop Launcher
- Open the application menu (press `Super`) and search for **PS3 MAC Checker**.
- Or open your file manager, navigate to `~/Arduino`, and double-click **Check_PS3_MAC.desktop**.

### 2. Command Line
Run directly in your terminal:
```bash
./ps3_mac_checker.sh
# or
python3 ps3_mac_checker.py
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

## Testing & Verification

The project includes an automated test battery with 75+ test cases covering hardware edge cases, third-party clone controller anomalies (Gasia/ShanWan/PanHai), udev hotplug races, ioctl encoding, and non-interactive environments:

```bash
# Run all automated tests (zero dependencies required)
python3 -m unittest discover -s tests -v
```

---

## Technical Details

Linux exposes HID devices via `/dev/hidraw*`. DualShock 3 controllers support specific HID feature reports:
- **Feature Report `0xF5` (Master bdaddr):** The controller returns an 8-byte structure containing the 6-byte Bluetooth address of the master host starting at offset 2.
- **Sysfs `uevent` / `HID_UNIQ`:** The Linux `hid-sony` kernel driver reads and reports the controller's physical Bluetooth device address.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
