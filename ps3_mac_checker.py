#!/usr/bin/env python3
"""
PS3 Controller MAC Address Checker
Reads Master MAC and Device MAC from Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers
via USB HID feature reports on Linux.

Author: Bagus Wijaya (Warsky)
Repository: https://github.com/chocowarsky/ps3-mac-checker
License: MIT
"""

import sys
import os
import glob
import time
import fcntl
import json
import argparse

__version__ = "1.1.0"

# Ensure line-buffered output so text appears immediately in terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


def HIDIOCGFEAT(size):
    """Compute ioctl number for Linux HIDIOCGFEAT(len)."""
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, size)
    return (3 << 30) | (size << 16) | (ord('H') << 8) | 0x07


def clear_screen():
    """Clear terminal screen if stdout is an interactive TTY and colors are allowed."""
    if (
        sys.stdout.isatty()
        and os.environ.get("TERM") != "dumb"
        and "NO_COLOR" not in os.environ
    ):
        sys.stdout.write("\033[H\033[J")
        sys.stdout.flush()


def get_ps3_devices():
    """
    Find sysfs device entries for connected PS3 controllers (Sony VID:PID 054C:0268).
    Deduplicates results and sorts paths deterministically.
    """
    patterns = [
        '/sys/bus/hid/devices/*054C:0268*',
        '/sys/bus/hid/devices/*054c:0268*',
    ]
    matches = set()
    for p in patterns:
        for match in glob.glob(p):
            matches.add(os.path.abspath(match))
    return sorted(list(matches))


def find_hidraw_node(device_path):
    """
    Find corresponding /dev/hidrawX character device node.
    Sorts deterministically to pick the canonical primary node.
    """
    hidraw_paths = glob.glob(os.path.join(device_path, 'hidraw', 'hidraw*'))
    if hidraw_paths:
        node_name = os.path.basename(sorted(hidraw_paths)[0])
        return f'/dev/{node_name}'
    return None


def read_device_mac(device_path):
    """
    Read physical Bluetooth Device MAC address of the controller.
    Falls back to sysfs input*/uniq if uevent HID_UNIQ is absent or empty.
    """
    # 1. Read HID_UNIQ from sysfs uevent
    uevent_file = os.path.join(device_path, 'uevent')
    if os.path.exists(uevent_file):
        try:
            with open(uevent_file, 'r', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('HID_UNIQ='):
                        val = line.split('=', 1)[1].strip()
                        if val:
                            return val.lower()
        except Exception:
            pass

    # 2. Fallback to sysfs input*/uniq
    uniq_files = glob.glob(os.path.join(device_path, 'input', 'input*', 'uniq'))
    if uniq_files and os.path.exists(uniq_files[0]):
        try:
            with open(uniq_files[0], 'r', errors='ignore') as f:
                content = f.read().strip()
                if content:
                    return content.lower()
        except Exception:
            pass

    return "Unavailable"


def validate_mac(mac_str):
    """
    Validate Bluetooth MAC address format and check for clone/unprogrammed controller signatures.
    Returns tuple (is_valid: bool, warning: str or None).
    """
    if not mac_str or mac_str == "Unavailable":
        return False, "MAC address unavailable"
    parts = mac_str.split(':')
    if len(parts) != 6:
        return False, "Malformed MAC address structure"
    try:
        byte_vals = [int(p, 16) for p in parts]
    except ValueError:
        return False, "Invalid hexadecimal digits in MAC"

    if all(b == 0 for b in byte_vals):
        return False, "Warning: Clone or uninitialized controller returned all zeros (00:00:00:00:00:00)"
    if all(b == 0xFF for b in byte_vals):
        return False, "Warning: Clone controller returned all 0xFF (unprogrammed EEPROM)"
    if byte_vals[0] & 0x01:
        return False, "Warning: Multicast bit is set (invalid for Bluetooth host address)"

    return True, None


def read_master_mac(devnode):
    """
    Read Master Host Bluetooth MAC stored inside PS3 controller memory.
    Uses HID Feature Report 0xF5 (similar to sixpair utility).
    Allocates 64-byte buffer for broad compatibility across clone controllers.
    """
    fd = os.open(devnode, os.O_RDWR)
    try:
        buf = bytearray([0xf5] + [0] * 63)
        fcntl.ioctl(fd, HIDIOCGFEAT(len(buf)), buf)
        mac_bytes = buf[2:8]
        return ':'.join(f'{b:02x}' for b in mac_bytes).lower()
    finally:
        os.close(fd)


def safe_input(prompt=""):
    """Prompt user safely; does nothing in non-interactive/closed-stdin environments."""
    if not sys.stdin.isatty():
        return ""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


def format_json(controllers_data):
    """Format controller inspection data as pretty JSON."""
    return json.dumps(controllers_data, indent=2)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="PS3 Controller MAC Address Checker for Linux (DualShock 3 / Sixaxis)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ps3_mac_checker.py              # Interactive mode
  ps3_mac_checker.py -j           # Output as JSON
  ps3_mac_checker.py -n -t 5      # Non-interactive, timeout after 5 seconds
  ps3_mac_checker.py --all        # Inspect all connected controllers
"""
    )
    parser.add_argument(
        '-j', '--json', action='store_true',
        help="Output results in JSON format"
    )
    parser.add_argument(
        '-n', '--non-interactive', action='store_true',
        help="Do not pause or prompt for Enter key before exiting"
    )
    parser.add_argument(
        '-t', '--timeout', type=float, default=None,
        help="Maximum seconds to wait for controller connection (default: wait indefinitely in interactive mode, 0 in non-interactive)"
    )
    parser.add_argument(
        '-a', '--all', action='store_true',
        help="Inspect all connected PS3 controllers instead of only the first"
    )
    parser.add_argument(
        '--no-sudo', action='store_true',
        help="Do not attempt automatic sudo re-elevation if permission is denied"
    )
    parser.add_argument(
        '-V', '--version', action='version', version=f"%(prog)s {__version__}"
    )
    args, _ = parser.parse_known_args(argv)
    return args


def inspect_controller(dev_path):
    """Inspect a single controller sysfs path and return its metadata dict."""
    devnode = find_hidraw_node(dev_path)
    device_mac = read_device_mac(dev_path)
    result = {
        "device_path": dev_path,
        "devnode": devnode,
        "device_mac": device_mac,
        "master_mac": None,
        "valid": False,
        "warning": None,
        "error": None
    }

    if not devnode or not os.path.exists(devnode):
        result["error"] = f"Device node not ready ({devnode})"
        return result

    try:
        master_mac = read_master_mac(devnode)
        result["master_mac"] = master_mac
        is_valid, warning = validate_mac(master_mac)
        result["valid"] = is_valid
        result["warning"] = warning
    except PermissionError:
        result["error"] = "Permission denied (udev rule required or run with sudo)"
    except Exception as e:
        result["error"] = str(e)

    return result


def main(argv=None):
    """Main program entry point."""
    args = parse_args(argv)

    if not args.json:
        clear_screen()
        print("============================================================")
        print("           PS3 CONTROLLER MAC ADDRESS CHECKER               ")
        print("============================================================")
        print()

    # Determine timeout
    timeout = args.timeout
    if timeout is None and (args.non_interactive or not sys.stdin.isatty()):
        timeout = 0.0

    start_time = time.time()
    devices = get_ps3_devices()

    if not devices:
        if not args.json:
            print("[i] Waiting for PS3 controller connection via USB cable...")
            print("    (Connect mini-USB cable to computer, or press Ctrl+C to cancel)")
        while not devices:
            if timeout is not None and (time.time() - start_time) >= timeout:
                if args.json:
                    print(format_json([]))
                else:
                    print(f"\n[!] Timeout ({timeout}s) reached. No PS3 controller detected.")
                return 1
            time.sleep(0.5)
            devices = get_ps3_devices()

    # Determine which devices to inspect
    target_devices = devices if args.all or len(devices) > 1 else [devices[0]]
    inspected = []
    permission_error_encountered = False

    for dev_path in target_devices:
        info = inspect_controller(dev_path)
        if info.get("error") and "Permission denied" in info["error"]:
            permission_error_encountered = True
        inspected.append(info)

    # Handle auto-sudo re-elevation if permission denied
    if permission_error_encountered and not args.no_sudo and os.geteuid() != 0 and not args.json:
        print("\n[*] Administrator privileges (sudo) required to read controller memory...")
        args_list = ['sudo', sys.executable] + sys.argv
        try:
            os.execvp('sudo', args_list)
        except Exception as e:
            print(f"[!] Failed to re-exec with sudo: {e}")
            return 2

    # JSON output mode
    if args.json:
        print(format_json(inspected))
        has_errors = any(item.get("error") for item in inspected)
        return 1 if has_errors else 0

    # Text output mode
    print(f"[✓] Detected {len(devices)} PS3 Controller(s)!\n")

    for idx, info in enumerate(inspected, 1):
        header = f"CONTROLLER #{idx}" if len(inspected) > 1 else "CONTROLLER DETAILS"
        print(f"--- {header} --------------------------------------")
        print(f"Hardware Path : {info['device_path']}")
        print(f"Device Node   : {info.get('devnode') or 'Not ready'}")

        if info.get("error"):
            if "Permission denied" in info["error"]:
                print(f"[!] Access denied to {info.get('devnode') or 'device'}: {info['error']}")
            else:
                print(f"[!] Error: {info['error']}")
        else:
            print(f"\n1. MASTER MAC (Required for ESP32 / Ps3.begin):")
            print(f"   >>  {info['master_mac']}  <<")
            if info.get("warning"):
                print(f"   [!] {info['warning']}")
            print(f"\n   Paste this into setup() in your Arduino IDE:")
            print(f'   Ps3.begin("{info["master_mac"]}");')

            print(f"\n2. DEVICE MAC (Physical Bluetooth Address of Controller):")
            print(f"   >>  {info['device_mac']}  <<")

        print("------------------------------------------------------------\n")

    if not args.non_interactive:
        safe_input("Done! Press [Enter] to close terminal...")

    has_errors = any(item.get("error") for item in inspected)
    return 1 if has_errors else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
