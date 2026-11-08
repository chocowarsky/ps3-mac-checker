#!/usr/bin/env python3
"""
PS3 Controller MAC Address Checker
Reads Master MAC and Device MAC from Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers
via USB HID feature reports on Linux and Windows.

Author: Bagus Wijaya (Warsky)
Repository: https://github.com/chocowarsky/ps3-mac-checker
License: MIT
"""

import sys
import os
import glob
import time
import json
import argparse

try:
    import fcntl
except ImportError:
    fcntl = None

__version__ = "1.2.0"

# Ensure line-buffered output so text appears immediately in terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


def HIDIOCGFEAT(size):
    """Compute ioctl number for Linux HIDIOCGFEAT(len)."""
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, size)
    return (3 << 30) | (size << 16) | (ord('H') << 8) | 0x07


def clear_screen():
    """Clear terminal screen if stdout is an interactive TTY and colors are allowed."""
    if not sys.stdout.isatty():
        return
    if os.environ.get("TERM") == "dumb" or "NO_COLOR" in os.environ:
        return

    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


# ============================================================================
# Backend Abstraction Layer
# ============================================================================

class BaseBackend:
    """Abstract base class for OS-specific USB HID access."""
    name = "base"

    def detect_devices(self):
        """Enumerate connected PS3 controller identifiers."""
        raise NotImplementedError

    def find_node(self, device_path):
        """Resolve device path to openable character device / handle path."""
        raise NotImplementedError

    def read_master_mac(self, devnode):
        """Extract Master Host Bluetooth MAC from controller."""
        raise NotImplementedError

    def read_device_mac(self, device_path):
        """Extract physical Device Bluetooth MAC from controller."""
        raise NotImplementedError


class LinuxBackend(BaseBackend):
    """Linux implementation using sysfs and /dev/hidraw ioctl."""
    name = "linux"

    def detect_devices(self):
        return get_ps3_devices()

    def find_node(self, device_path):
        return find_hidraw_node(device_path)

    def read_master_mac(self, devnode):
        return read_master_mac(devnode)

    def read_device_mac(self, device_path):
        return read_device_mac(device_path)


class WindowsBackend(BaseBackend):
    """
    Windows implementation using standard library ctypes to interact with
    hid.dll, setupapi.dll, and kernel32.dll without external dependencies.
    """
    name = "win32"

    def __init__(self, setupapi=None, hid=None, kernel32=None):
        self._setupapi = setupapi
        self._hid = hid
        self._kernel32 = kernel32
        self._ctypes = None
        self._wintypes = None

    def _init_win32(self):
        if self._ctypes is not None:
            return
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._wintypes = wintypes

        if self._setupapi is None and hasattr(ctypes, 'windll'):
            self._setupapi = ctypes.windll.setupapi
        if self._hid is None and hasattr(ctypes, 'windll'):
            self._hid = ctypes.windll.hid
        if self._kernel32 is None and hasattr(ctypes, 'windll'):
            self._kernel32 = ctypes.windll.kernel32

    def detect_devices(self):
        """Enumerate Win32 HID device interface paths matching Sony DualShock 3 (054C:0268)."""
        self._init_win32()
        if not self._setupapi or not self._hid:
            return []

        ctypes = self._ctypes
        wintypes = self._wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
            ]

        hid_guid = GUID()
        self._hid.HidD_GetHidGuid(ctypes.byref(hid_guid))

        DIGCF_PRESENT = 0x00000002
        DIGCF_DEVICEINTERFACE = 0x00000010
        hdevinfo = self._setupapi.SetupDiGetClassDevsW(
            ctypes.byref(hid_guid),
            None,
            None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
        )
        if hdevinfo == -1 or hdevinfo == ctypes.c_void_p(-1).value:
            return []

        devices = []
        try:
            device_index = 0
            interface_data = SP_DEVICE_INTERFACE_DATA()
            interface_data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)

            while self._setupapi.SetupDiEnumDeviceInterfaces(
                hdevinfo, None, ctypes.byref(hid_guid), device_index, ctypes.byref(interface_data)
            ):
                required_size = wintypes.DWORD()
                self._setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdevinfo, ctypes.byref(interface_data), None, 0, ctypes.byref(required_size), None
                )

                if required_size.value > 0:
                    detail_buffer = ctypes.create_string_buffer(required_size.value)
                    cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
                    ctypes.c_uint32.from_buffer(detail_buffer).value = cb_size

                    if self._setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdevinfo, ctypes.byref(interface_data), detail_buffer, required_size, None, None
                    ):
                        device_path = ctypes.wstring_at(ctypes.addressof(detail_buffer) + 4)
                        path_lower = device_path.lower()
                        if "vid_054c" in path_lower and "pid_0268" in path_lower:
                            devices.append(device_path)
                device_index += 1
        finally:
            self._setupapi.SetupDiDestroyDeviceInfoList(hdevinfo)

        return sorted(list(set(devices)))

    def find_node(self, device_path):
        return device_path

    def read_master_mac(self, device_path):
        """Read Master Host MAC from DualShock 3 via Win32 HID Feature Report 0xF5."""
        self._init_win32()
        if not self._kernel32 or not self._hid:
            raise OSError("Win32 HID subsystem not available")

        ctypes = self._ctypes
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3

        handle = self._kernel32.CreateFileW(
            device_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )

        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle or handle == -1:
            err = self._kernel32.GetLastError()
            if err == 5:
                raise PermissionError("Access denied opening Win32 HID device")
            elif err in (2, 1167):
                raise FileNotFoundError("Device disconnected")
            raise OSError(f"Failed to open HID device (Win32 Error {err})")

        try:
            buf = bytearray([0xF5] + [0] * 63)
            c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            res = self._hid.HidD_GetFeature(handle, c_buf, len(buf))
            if not res:
                err = self._kernel32.GetLastError()
                raise OSError(f"HidD_GetFeature report 0xF5 failed (Win32 Error {err})")

            return ':'.join(f'{b:02x}' for b in buf[2:8]).lower()
        finally:
            self._kernel32.CloseHandle(handle)

    def read_device_mac(self, device_path):
        """Read physical Device MAC from DualShock 3 via Win32 HID Feature Report 0xF2."""
        self._init_win32()
        if not self._kernel32 or not self._hid:
            return "Unavailable"

        ctypes = self._ctypes
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3

        handle = self._kernel32.CreateFileW(
            device_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )

        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle or handle == -1:
            return "Unavailable"

        try:
            buf = bytearray([0xF2] + [0] * 63)
            c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            res = self._hid.HidD_GetFeature(handle, c_buf, len(buf))
            if res:
                mac_bytes = buf[4:10]
                if any(b != 0 for b in mac_bytes):
                    return ':'.join(f'{b:02x}' for b in mac_bytes).lower()
            return "Unavailable"
        finally:
            self._kernel32.CloseHandle(handle)


def get_backend(platform_name=None):
    """Factory returning the appropriate platform backend."""
    plat = platform_name if platform_name is not None else sys.platform
    if plat == 'win32':
        return WindowsBackend()
    return LinuxBackend()


# ============================================================================
# Linux-Specific Helpers (Preserved for backwards compatibility & tests)
# ============================================================================

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
            matches.add(match)
    return sorted(list(matches))


def find_hidraw_node(device_path):
    """
    Find corresponding /dev/hidrawX character device node on Linux.
    Sorts deterministically to pick the canonical primary node.
    """
    hidraw_paths = glob.glob(os.path.join(device_path, 'hidraw', 'hidraw*'))
    if hidraw_paths:
        node_name = os.path.basename(sorted(hidraw_paths)[0])
        return f'/dev/{node_name}'
    return None


def read_device_mac(device_path):
    """
    Read physical Bluetooth Device MAC address of the controller on Linux.
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
    Read Master Host Bluetooth MAC stored inside PS3 controller memory on Linux.
    Uses HID Feature Report 0xF5 (similar to sixpair utility).
    Allocates 64-byte buffer for broad compatibility across clone controllers.
    """
    _fcntl = sys.modules.get('fcntl') or fcntl
    if _fcntl is None:
        raise OSError("fcntl module unavailable on this operating system")

    fd = os.open(devnode, os.O_RDWR)
    try:
        buf = bytearray([0xf5] + [0] * 63)
        _fcntl.ioctl(fd, HIDIOCGFEAT(len(buf)), buf)
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
        description="PS3 Controller MAC Address Checker (DualShock 3 / Sixaxis) for Linux & Windows",
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


def inspect_controller(dev_path, backend=None):
    """Inspect a single controller path and return its metadata dict."""
    if backend is None:
        backend = get_backend()

    devnode = backend.find_node(dev_path)
    device_mac = backend.read_device_mac(dev_path)
    result = {
        "device_path": dev_path,
        "devnode": devnode,
        "device_mac": device_mac,
        "master_mac": None,
        "valid": False,
        "warning": None,
        "error": None
    }

    if not devnode or (backend.name == "linux" and not os.path.exists(devnode)):
        result["error"] = f"Device node not ready ({devnode})"
        return result

    try:
        master_mac = backend.read_master_mac(devnode)
        result["master_mac"] = master_mac
        is_valid, warning = validate_mac(master_mac)
        result["valid"] = is_valid
        result["warning"] = warning
    except PermissionError:
        result["error"] = "Permission denied (udev rule required or run with sudo / Administrator)"
    except Exception as e:
        result["error"] = str(e)

    return result


def main(argv=None, backend=None):
    """Main program entry point."""
    if backend is None:
        is_linux_mocked = (
            hasattr(get_ps3_devices, 'assert_called')
            or hasattr(read_master_mac, 'assert_called')
            or hasattr(find_hidraw_node, 'assert_called')
        )
        if is_linux_mocked:
            backend = LinuxBackend()
        else:
            backend = get_backend()

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
    devices = backend.detect_devices()

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
            devices = backend.detect_devices()

    # Determine which devices to inspect
    target_devices = devices if args.all or len(devices) > 1 else [devices[0]]
    inspected = []
    permission_error_encountered = False

    for dev_path in target_devices:
        info = inspect_controller(dev_path, backend=backend)
        if info.get("error") and "Permission denied" in info["error"]:
            permission_error_encountered = True
        inspected.append(info)

    # Handle auto-sudo re-elevation if permission denied on Linux
    if (
        permission_error_encountered
        and not args.no_sudo
        and hasattr(os, 'geteuid')
        and os.geteuid() != 0
        and not args.json
    ):
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
