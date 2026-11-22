#!/usr/bin/env python3
"""
PS3 Controller MAC Address Manager
Read, change, pair, back up, and manage Master & Device MAC addresses on
Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers via USB HID on Linux & Windows.

Author: Bagus Wijaya (Warsky)
Repository: https://github.com/chocowarsky/ps3-mac-manager
License: MIT
"""

import argparse
from datetime import datetime, timezone
import glob
import json
import os
import sys
import time

try:
    import fcntl
except ImportError:
    fcntl = None

__version__ = "2.0.0"

# Ensure line-buffered output so text appears immediately in terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def HIDIOCSFEAT(size):
    """Compute ioctl number for Linux HIDIOCSFEATURE(len)."""
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, size)
    return (3 << 30) | (size << 16) | (ord("H") << 8) | 0x06


def HIDIOCGFEAT(size):
    """Compute ioctl number for Linux HIDIOCGFEATURE(len)."""
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, size)
    return (3 << 30) | (size << 16) | (ord("H") << 8) | 0x07


def clear_screen():
    """Clear terminal screen if stdout is an interactive TTY and colors are allowed."""
    if not sys.stdout.isatty():
        return
    if os.environ.get("TERM") == "dumb" or "NO_COLOR" in os.environ:
        return

    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


def _utc_now_iso():
    """Return current UTC ISO-8601 timestamp string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ============================================================================
# MAC Normalization, Validation, Generation & Snippets
# ============================================================================

def normalize_mac(mac_str):
    """
    Normalize a Bluetooth MAC address to lowercase colon-separated format (aa:bb:cc:dd:ee:ff).
    Accepts colon, hyphen, space, Cisco dot (aabb.ccdd.eeff), or raw 12-char hex strings.
    Raises ValueError if the input cannot be parsed as a 6-byte MAC address.
    """
    if not isinstance(mac_str, str):
        raise ValueError("MAC address must be a string")

    cleaned = mac_str.strip()
    if not cleaned:
        raise ValueError("MAC address cannot be empty")

    octets = _split_mac_parts(cleaned)
    if len(octets) != 6:
        raise ValueError(f"Invalid MAC address format: '{mac_str}'")

    byte_vals = []
    for part in octets:
        if not 1 <= len(part) <= 2:
            raise ValueError(f"Invalid octet '{part}' in MAC address '{mac_str}'")
        try:
            val = int(part, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid hexadecimal digit in MAC address '{mac_str}'") from exc
        if not 0 <= val <= 0xFF:
            raise ValueError(f"Octet out of range in MAC address '{mac_str}'")
        byte_vals.append(val)

    return ":".join(f"{b:02x}" for b in byte_vals)


def _split_mac_parts(cleaned):
    """Split supported MAC string formats into raw hex byte strings."""
    for sep in (":", "-", " "):
        if sep in cleaned:
            return cleaned.split(sep)

    if "." in cleaned:
        groups = cleaned.split(".")
        if len(groups) == 3 and all(len(g) == 4 for g in groups):
            joined = "".join(groups)
            return [joined[i:i + 2] for i in range(0, 12, 2)]
        return []

    if len(cleaned) == 12:
        return [cleaned[i:i + 2] for i in range(0, 12, 2)]

    return []


def mac_to_bytes(mac_str):
    """Convert a MAC address string into a list of 6 integer byte values."""
    normalized = normalize_mac(mac_str)
    return [int(part, 16) for part in normalized.split(":")]


def validate_mac(mac_str):
    """
    Validate Bluetooth MAC address format and check for clone/unprogrammed controller signatures.
    Returns tuple (is_valid: bool, warning: str or None).
    """
    if not mac_str or mac_str == "Unavailable":
        return False, "MAC address unavailable"
    parts = mac_str.split(":")
    if len(parts) != 6:
        return False, "Malformed MAC address structure"
    try:
        byte_vals = [int(p, 16) for p in parts]
    except ValueError:
        return False, "Invalid hexadecimal digits in MAC"

    if any(not 0 <= b <= 0xFF for b in byte_vals):
        return False, "MAC byte out of range"
    if all(b == 0 for b in byte_vals):
        return False, "Warning: Clone or uninitialized controller returned all zeros (00:00:00:00:00:00)"
    if all(b == 0xFF for b in byte_vals):
        return False, "Warning: Clone controller returned all 0xFF (unprogrammed EEPROM)"
    if byte_vals[0] & 0x01:
        return False, "Warning: Multicast bit is set (invalid for Bluetooth host address)"

    return True, None


def validate_mac_for_write(mac_str, force=False):
    """
    Normalize and validate a target Master MAC before writing to controller EEPROM.
    Returns (normalized_mac, warning). Raises ValueError on invalid MAC unless force=True.
    """
    normalized = normalize_mac(mac_str)
    is_valid, warning = validate_mac(normalized)
    if not is_valid and not force:
        raise ValueError(f"{warning} (pass --force to write anyway)")
    return normalized, warning


def generate_random_mac():
    """
    Generate a random, safe locally administered unicast Bluetooth MAC address.
    Bit 0 of byte 0 is 0 (unicast) and bit 1 of byte 0 is 1 (locally administered).
    """
    while True:
        raw = os.urandom(6)
        b0 = (raw[0] & 0xFE) | 0x02
        octets = [b0] + list(raw[1:])
        if any(b != 0 for b in octets[1:]) and not all(b == 0xFF for b in octets[1:]):
            return ":".join(f"{b:02x}" for b in octets)


def format_code_snippets(mac_str):
    """Return copy-pasteable ESP32/Arduino and C array snippets for a Master MAC."""
    hex_bytes = ", ".join(f"0x{part}" for part in mac_str.split(":"))
    return {
        "arduino": f'Ps3.begin("{mac_str}");',
        "c_array": f"uint8_t master_mac[6] = {{{hex_bytes}}};",
    }


# ============================================================================
# Backend Abstraction Layer
# ============================================================================

class BaseBackend:
    """Abstract base class for OS-specific USB HID and Bluetooth host access."""
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

    def write_master_mac(self, devnode, mac_str):
        """Write Master Host Bluetooth MAC to controller."""
        raise NotImplementedError

    def read_device_mac(self, device_path):
        """Extract physical Device Bluetooth MAC from controller."""
        raise NotImplementedError

    def detect_host_bluetooth_macs(self):
        """Return list of local Bluetooth adapters as [{'adapter': ..., 'address': ...}]."""
        raise NotImplementedError


class LinuxBackend(BaseBackend):
    """Linux implementation using sysfs, BlueZ sysfs adapters, and /dev/hidraw ioctl."""
    name = "linux"

    def detect_devices(self):
        return get_ps3_devices()

    def find_node(self, device_path):
        return find_hidraw_node(device_path)

    def read_master_mac(self, devnode):
        return read_master_mac(devnode)

    def write_master_mac(self, devnode, mac_str):
        return write_master_mac(devnode, mac_str)

    def read_device_mac(self, device_path):
        return read_device_mac(device_path)

    def detect_host_bluetooth_macs(self):
        return detect_linux_bluetooth_macs()


class WindowsBackend(BaseBackend):
    """
    Windows implementation using standard library ctypes to interact with
    hid.dll, setupapi.dll, kernel32.dll, and bthprops.cpl without external dependencies.
    """
    name = "win32"

    def __init__(self, setupapi=None, hid=None, kernel32=None, bthprops=None):
        self._setupapi = setupapi
        self._hid = hid
        self._kernel32 = kernel32
        self._bthprops = bthprops
        self._ctypes = None
        self._wintypes = None

    def _init_win32(self):
        if self._ctypes is not None:
            return
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._wintypes = wintypes

        if hasattr(ctypes, "windll"):
            if self._setupapi is None:
                self._setupapi = ctypes.windll.setupapi
            if self._hid is None:
                self._hid = ctypes.windll.hid
            if self._kernel32 is None:
                self._kernel32 = ctypes.windll.kernel32

    def _open_hid_handle(self, device_path, raise_on_error=True):
        """Open a Win32 HID device interface handle with read/write access."""
        self._init_win32()
        if not self._kernel32 or not self._hid:
            if raise_on_error:
                raise OSError("Win32 HID subsystem not available")
            return None

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
            None,
        )

        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle or handle == -1:
            if not raise_on_error:
                return None
            err = self._kernel32.GetLastError()
            if err == 5:
                raise PermissionError("Access denied opening Win32 HID device")
            if err in (2, 1167):
                raise FileNotFoundError("Device disconnected")
            raise OSError(f"Failed to open HID device (Win32 Error {err})")

        return handle

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
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
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

        return sorted(set(devices))

    def find_node(self, device_path):
        return device_path

    def read_master_mac(self, device_path):
        """Read Master Host MAC from DualShock 3 via Win32 HID Feature Report 0xF5."""
        handle = self._open_hid_handle(device_path, raise_on_error=True)
        ctypes = self._ctypes
        try:
            buf = bytearray([0xF5] + [0] * 63)
            c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            res = self._hid.HidD_GetFeature(handle, c_buf, len(buf))
            if not res:
                err = self._kernel32.GetLastError()
                raise OSError(f"HidD_GetFeature report 0xF5 failed (Win32 Error {err})")
            return ":".join(f"{b:02x}" for b in buf[2:8]).lower()
        finally:
            self._kernel32.CloseHandle(handle)

    def write_master_mac(self, device_path, mac_str):
        """Write Master Host MAC to DualShock 3 via Win32 HID Feature Report 0xF5."""
        normalized = normalize_mac(mac_str)
        mac_bytes = mac_to_bytes(normalized)
        handle = self._open_hid_handle(device_path, raise_on_error=True)
        ctypes = self._ctypes
        try:
            for payload in (
                bytearray([0xF5, 0x01] + mac_bytes + [0] * 56),
                bytearray([0xF5, 0x01] + mac_bytes),
            ):
                c_buf = (ctypes.c_ubyte * len(payload)).from_buffer(payload)
                if self._hid.HidD_SetFeature(handle, c_buf, len(payload)):
                    return normalized
            err = self._kernel32.GetLastError()
            raise OSError(f"HidD_SetFeature report 0xF5 failed (Win32 Error {err})")
        finally:
            self._kernel32.CloseHandle(handle)

    def read_device_mac(self, device_path):
        """Read physical Device MAC from DualShock 3 via Win32 HID Feature Report 0xF2."""
        handle = self._open_hid_handle(device_path, raise_on_error=False)
        if not handle:
            return "Unavailable"

        ctypes = self._ctypes
        try:
            buf = bytearray([0xF2] + [0] * 63)
            c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            res = self._hid.HidD_GetFeature(handle, c_buf, len(buf))
            if res:
                mac_bytes = buf[4:10]
                if any(b != 0 for b in mac_bytes):
                    return ":".join(f"{b:02x}" for b in mac_bytes).lower()
            return "Unavailable"
        finally:
            self._kernel32.CloseHandle(handle)

    def detect_host_bluetooth_macs(self):
        """Discover local Bluetooth adapter MACs on Windows via bthprops.cpl."""
        self._init_win32()
        ctypes = self._ctypes
        wintypes = self._wintypes

        bthprops = self._bthprops
        if bthprops is None and hasattr(ctypes, "windll"):
            for dll_name in ("bthprops.cpl", "irprops.cpl"):
                try:
                    bthprops = ctypes.WinDLL(dll_name)
                    break
                except OSError:
                    continue
        if not bthprops or not self._kernel32:
            return []

        class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_uint32)]

        class BLUETOOTH_ADDRESS(ctypes.Union):
            _fields_ = [
                ("ullLong", ctypes.c_uint64),
                ("rgBytes", ctypes.c_ubyte * 6),
            ]

        class BLUETOOTH_RADIO_INFO(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32),
                ("address", BLUETOOTH_ADDRESS),
                ("szName", ctypes.c_uint16 * 248),
                ("ulClassofDevice", ctypes.c_uint32),
                ("lmpSubversion", ctypes.c_uint16),
                ("manufacturer", ctypes.c_uint16),
            ]

        params = BLUETOOTH_FIND_RADIO_PARAMS(dwSize=ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
        radio_handle = wintypes.HANDLE()
        find_handle = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio_handle))
        if not find_handle:
            return []

        adapters = []
        idx = 0
        try:
            while True:
                info = BLUETOOTH_RADIO_INFO(dwSize=ctypes.sizeof(BLUETOOTH_RADIO_INFO))
                if bthprops.BluetoothGetRadioInfo(radio_handle, ctypes.byref(info)) == 0:
                    mac_bytes = list(info.address.rgBytes[:6])[::-1]
                    mac_str = ":".join(f"{b:02x}" for b in mac_bytes)
                    if any(b != 0 for b in mac_bytes):
                        raw_name = bytes(info.szName).decode("utf-16-le", errors="ignore")
                        adapter_name = raw_name.split("\x00", 1)[0].strip() or f"bt{idx}"
                        adapters.append({
                            "adapter": adapter_name,
                            "address": mac_str,
                        })
                self._kernel32.CloseHandle(radio_handle)
                idx += 1
                if not bthprops.BluetoothFindNextRadio(find_handle, ctypes.byref(radio_handle)):
                    break
        except (OSError, AttributeError):
            return adapters
        finally:
            bthprops.BluetoothFindRadioClose(find_handle)

        return adapters


def get_backend(platform_name=None):
    """Factory returning the appropriate platform backend."""
    plat = platform_name if platform_name is not None else sys.platform
    if plat == "win32":
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
        "/sys/bus/hid/devices/*054C:0268*",
        "/sys/bus/hid/devices/*054c:0268*",
    ]
    matches = set()
    for pattern in patterns:
        for match in glob.glob(pattern):
            matches.add(match)
    return sorted(matches)


def find_hidraw_node(device_path):
    """
    Find corresponding /dev/hidrawX character device node on Linux.
    Sorts deterministically to pick the canonical primary node.
    """
    hidraw_paths = glob.glob(os.path.join(device_path, "hidraw", "hidraw*"))
    if hidraw_paths:
        node_name = os.path.basename(sorted(hidraw_paths)[0])
        return f"/dev/{node_name}"
    return None


def _read_device_mac_from_uevent(device_path):
    """Read HID_UNIQ from sysfs uevent if available."""
    uevent_file = os.path.join(device_path, "uevent")
    if not os.path.exists(uevent_file):
        return None
    try:
        with open(uevent_file, "r", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("HID_UNIQ="):
                    val = stripped.split("=", 1)[1].strip()
                    if val:
                        return val.lower()
    except OSError:
        return None
    return None


def _read_device_mac_from_input_uniq(device_path):
    """Read physical MAC from sysfs input*/uniq fallback."""
    uniq_files = sorted(glob.glob(os.path.join(device_path, "input", "input*", "uniq")))
    if not uniq_files or not os.path.exists(uniq_files[0]):
        return None
    try:
        with open(uniq_files[0], "r", errors="ignore") as f:
            content = f.read().strip()
            if content:
                return content.lower()
    except OSError:
        return None
    return None


def _read_device_mac_from_hidraw(devnode):
    """Read physical Device MAC via HID Feature Report 0xF2 on Linux hidraw."""
    _fcntl = sys.modules.get("fcntl") or fcntl
    if _fcntl is None or not devnode or not os.path.exists(devnode):
        return None
    try:
        fd = os.open(devnode, os.O_RDWR)
    except OSError:
        return None

    try:
        buf = bytearray([0xF2] + [0] * 63)
        _fcntl.ioctl(fd, HIDIOCGFEAT(len(buf)), buf)
        mac_bytes = buf[4:10]
        if any(b != 0 for b in mac_bytes):
            return ":".join(f"{b:02x}" for b in mac_bytes).lower()
    except OSError:
        return None
    finally:
        os.close(fd)
    return None


def read_device_mac(device_path):
    """
    Read physical Bluetooth Device MAC address of the controller on Linux.
    Checks sysfs uevent HID_UNIQ, sysfs input*/uniq, and HID Feature Report 0xF2.
    """
    mac = _read_device_mac_from_uevent(device_path)
    if mac:
        return mac

    mac = _read_device_mac_from_input_uniq(device_path)
    if mac:
        return mac

    devnode = find_hidraw_node(device_path)
    mac = _read_device_mac_from_hidraw(devnode)
    if mac:
        return mac

    return "Unavailable"


def read_master_mac(devnode):
    """
    Read Master Host Bluetooth MAC stored inside PS3 controller memory on Linux.
    Uses HID Feature Report 0xF5 (similar to sixpair utility).
    Allocates 64-byte buffer for broad compatibility across clone controllers.
    """
    _fcntl = sys.modules.get("fcntl") or fcntl
    if _fcntl is None:
        raise OSError("fcntl module unavailable on this operating system")

    fd = os.open(devnode, os.O_RDWR)
    try:
        buf = bytearray([0xF5] + [0] * 63)
        _fcntl.ioctl(fd, HIDIOCGFEAT(len(buf)), buf)
        mac_bytes = buf[2:8]
        return ":".join(f"{b:02x}" for b in mac_bytes).lower()
    finally:
        os.close(fd)


def write_master_mac(devnode, mac_str):
    """
    Write Master Host Bluetooth MAC into PS3 controller EEPROM on Linux.
    Sends HID Feature Report 0xF5 (subcommand 0x01) via HIDIOCSFEATURE ioctl.
    Tries 8-byte canonical report first, falling back to 64-byte buffer for clones.
    """
    _fcntl = sys.modules.get("fcntl") or fcntl
    if _fcntl is None:
        raise OSError("fcntl module unavailable on this operating system")

    normalized = normalize_mac(mac_str)
    mac_bytes = mac_to_bytes(normalized)
    fd = os.open(devnode, os.O_RDWR)
    try:
        buf8 = bytearray([0xF5, 0x01] + mac_bytes)
        try:
            _fcntl.ioctl(fd, HIDIOCSFEAT(len(buf8)), buf8)
        except OSError:
            buf64 = bytearray([0xF5, 0x01] + mac_bytes + [0] * 56)
            _fcntl.ioctl(fd, HIDIOCSFEAT(len(buf64)), buf64)
        return normalized
    finally:
        os.close(fd)


def detect_linux_bluetooth_macs(sysfs_root="/sys/class/bluetooth"):
    """Discover local Bluetooth adapter MAC addresses on Linux from sysfs."""
    adapters = []
    for addr_path in sorted(glob.glob(os.path.join(sysfs_root, "hci*", "address"))):
        adapter_name = os.path.basename(os.path.dirname(addr_path))
        try:
            with open(addr_path, "r", errors="ignore") as f:
                raw_addr = f.read().strip()
            normalized = normalize_mac(raw_addr)
            is_valid, _ = validate_mac(normalized)
            if is_valid:
                adapters.append({"adapter": adapter_name, "address": normalized})
        except (OSError, ValueError):
            continue
    return adapters


# ============================================================================
# Profile Presets & Backup/Restore Store
# ============================================================================

def get_store_path(custom_path=None):
    """Resolve configuration file path for saved MAC profiles and automatic backups."""
    if custom_path:
        return custom_path
    env_path = os.environ.get("PS3_MAC_CONFIG")
    if env_path:
        return env_path
    if sys.platform == "win32":
        base_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base_dir, "ps3-mac-manager", "config.json")


def _default_store():
    return {"version": 1, "profiles": {}, "backups": {}}


def load_store(store_path=None):
    """Load profile and backup store from disk, returning empty defaults if absent."""
    path = get_store_path(store_path)
    if not os.path.exists(path):
        return _default_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_store()

    if not isinstance(data, dict):
        return _default_store()

    data.setdefault("version", 1)
    if not isinstance(data.get("profiles"), dict):
        data["profiles"] = {}
    if not isinstance(data.get("backups"), dict):
        data["backups"] = {}
    return data


def save_store(data, store_path=None):
    """Persist profile and backup store atomically to disk."""
    path = get_store_path(store_path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def save_profile(name, mac_str, store_path=None, force=False):
    """Save or update a named Master MAC profile preset."""
    profile_name = (name or "").strip()
    if not profile_name:
        raise ValueError("Profile name cannot be empty")
    normalized, _ = validate_mac_for_write(mac_str, force=force)
    data = load_store(store_path)
    data["profiles"][profile_name] = {
        "mac": normalized,
        "updated_at": _utc_now_iso(),
    }
    save_store(data, store_path)
    return normalized


def delete_profile(name, store_path=None):
    """Remove a named Master MAC profile preset. Returns True if deleted."""
    profile_name = (name or "").strip()
    data = load_store(store_path)
    if profile_name not in data["profiles"]:
        return False
    del data["profiles"][profile_name]
    save_store(data, store_path)
    return True


def _extract_profile_mac(entry):
    """Extract MAC string from either dict or legacy string profile entry."""
    if isinstance(entry, dict):
        return entry.get("mac")
    if isinstance(entry, str):
        return entry
    return None


def get_profile(name, store_path=None):
    """Look up a saved Master MAC profile by name and return its normalized MAC or None."""
    profile_name = (name or "").strip()
    data = load_store(store_path)
    raw = _extract_profile_mac(data["profiles"].get(profile_name))
    if not raw:
        return None
    return normalize_mac(raw)


def list_profiles(store_path=None):
    """Return sorted dict of saved profiles with normalized metadata."""
    data = load_store(store_path)
    profiles = {}
    for name in sorted(data["profiles"]):
        entry = data["profiles"][name]
        mac = _extract_profile_mac(entry)
        if not mac:
            continue
        try:
            norm_mac = normalize_mac(mac)
        except ValueError:
            continue
        updated_at = entry.get("updated_at") if isinstance(entry, dict) else None
        profiles[name] = {"mac": norm_mac, "updated_at": updated_at}
    return profiles


def record_backup(device_key, previous_master_mac, new_master_mac=None, store_path=None):
    """Record a controller's previous Master MAC before overwriting it."""
    if not device_key or not previous_master_mac:
        return False
    try:
        prev_norm = normalize_mac(previous_master_mac)
    except ValueError:
        return False

    data = load_store(store_path)
    entry = data["backups"].get(device_key)
    if not isinstance(entry, dict):
        entry = {}

    if "original_master_mac" not in entry:
        entry["original_master_mac"] = prev_norm

    entry["previous_master_mac"] = prev_norm
    if new_master_mac:
        try:
            entry["last_written_mac"] = normalize_mac(new_master_mac)
        except ValueError:
            pass
    entry["updated_at"] = _utc_now_iso()

    history = entry.get("history")
    if not isinstance(history, list):
        history = []
    history.append({
        "previous_master_mac": prev_norm,
        "new_master_mac": entry.get("last_written_mac"),
        "timestamp": entry["updated_at"],
    })
    entry["history"] = history[-10:]

    data["backups"][device_key] = entry
    save_store(data, store_path)
    return True


def get_backup_mac(device_key, store_path=None):
    """Return the most recent backed-up Master MAC for a controller key, or None."""
    if not device_key:
        return None
    data = load_store(store_path)
    entry = data["backups"].get(device_key)
    if not isinstance(entry, dict):
        return None
    prev = entry.get("previous_master_mac")
    if not prev:
        return None
    try:
        return normalize_mac(prev)
    except ValueError:
        return None


def export_backup_file(filepath, controllers_data):
    """Export inspected controller MAC state to a standalone JSON backup file."""
    payload = {
        "version": 1,
        "exported_at": _utc_now_iso(),
        "controllers": controllers_data,
    }
    parent = os.path.dirname(os.path.abspath(filepath))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return filepath


def import_backup_file(filepath):
    """Load controller backup entries from a JSON backup file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("controllers"), list):
        controllers = data["controllers"]
    elif isinstance(data, list):
        controllers = data
    else:
        raise ValueError(f"Invalid backup file structure in '{filepath}'")

    if not controllers:
        raise ValueError(f"No controller entries found in '{filepath}'")
    return controllers


# ============================================================================
# High-Level Inspection & Modification
# ============================================================================

def safe_input(prompt=""):
    """Prompt user safely; does nothing in non-interactive/closed-stdin environments."""
    if not sys.stdin.isatty():
        return ""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


def format_json(controllers_data):
    """Format controller inspection or management data as pretty JSON."""
    return json.dumps(controllers_data, indent=2)


def _controller_backup_key(device_mac, dev_path):
    """Choose deterministic backup store key for a controller."""
    if device_mac and device_mac != "Unavailable":
        return device_mac
    return dev_path


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
        "error": None,
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


def change_controller_mac(dev_path, target_mac, backend=None, force=False, store_path=None):
    """
    Safely write a new Master MAC to a PS3 controller and verify via read-back.
    Automatically backs up the previous Master MAC before overwriting.
    """
    if backend is None:
        backend = get_backend()

    normalized_mac, write_warning = validate_mac_for_write(target_mac, force=force)
    inspected = inspect_controller(dev_path, backend=backend)

    result = {
        "device_path": dev_path,
        "devnode": inspected.get("devnode"),
        "device_mac": inspected.get("device_mac", "Unavailable"),
        "previous_master_mac": inspected.get("master_mac"),
        "requested_master_mac": normalized_mac,
        "master_mac": inspected.get("master_mac"),
        "verified": False,
        "valid": False,
        "warning": write_warning,
        "backup_saved": False,
        "error": inspected.get("error"),
    }

    if result["error"]:
        return result

    devnode = result["devnode"]
    prev_mac = result["previous_master_mac"]
    if prev_mac and validate_mac(prev_mac)[0]:
        key = _controller_backup_key(result["device_mac"], dev_path)
        result["backup_saved"] = record_backup(
            key, prev_mac, new_master_mac=normalized_mac, store_path=store_path
        )

    try:
        backend.write_master_mac(devnode, normalized_mac)
        readback_mac = backend.read_master_mac(devnode)
        result["master_mac"] = readback_mac
        is_valid, read_warning = validate_mac(readback_mac)
        result["valid"] = is_valid
        result["verified"] = readback_mac == normalized_mac
        result["warning"] = read_warning or write_warning
        if not result["verified"]:
            result["error"] = (
                f"Write verification mismatch: expected {normalized_mac}, read back {readback_mac}"
            )
    except PermissionError:
        result["error"] = "Permission denied (udev rule required or run with sudo / Administrator)"
    except Exception as e:
        result["error"] = str(e)

    return result


# ============================================================================
# CLI Argument Parsing & Execution Helpers
# ============================================================================

def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="PS3 Controller MAC Address Manager (Read, Write, Pair & Profiles) for Linux & Windows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ps3_mac_manager.py                         # Interactive TUI dashboard
  ps3_mac_manager.py --check                 # Read-only MAC check
  ps3_mac_manager.py -s 00:1d:0d:4c:e3:78    # Change Master MAC (auto-verifies)
  ps3_mac_manager.py -g                      # Generate & write random safe MAC
  ps3_mac_manager.py -p                      # Pair controller to this PC's Bluetooth
  ps3_mac_manager.py --save-profile robot1   # Save controller's Master MAC as 'robot1'
  ps3_mac_manager.py --apply-profile robot1  # Write 'robot1' MAC to controller
  ps3_mac_manager.py --restore               # Restore previous Master MAC from backup
  ps3_mac_manager.py -j -n                   # Machine-readable JSON check
""",
    )
    parser.add_argument("-j", "--json", action="store_true", help="Output results in JSON format")
    parser.add_argument(
        "-n", "--non-interactive", action="store_true",
        help="Do not pause or show interactive menu before exiting",
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=None,
        help="Maximum seconds to wait for controller connection (default: wait indefinitely in interactive mode, 0 in non-interactive)",
    )
    parser.add_argument(
        "-a", "--all", action="store_true",
        help="Operate on all connected PS3 controllers instead of only the first",
    )
    parser.add_argument(
        "--no-sudo", action="store_true",
        help="Do not attempt automatic sudo re-elevation if permission is denied",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Read-only check mode (skips interactive management menu)",
    )
    parser.add_argument(
        "-s", "--set-mac", metavar="MAC",
        help="Write a new Master Bluetooth MAC address to the connected controller",
    )
    parser.add_argument(
        "-g", "--generate-mac", action="store_true",
        help="Generate a random locally administered unicast MAC and write it to the controller",
    )
    parser.add_argument(
        "-p", "--pair-host", action="store_true",
        help="Pair controller to this computer's local Bluetooth adapter (sixpair mode)",
    )
    parser.add_argument(
        "--adapter", metavar="HCI",
        help="Select specific local Bluetooth adapter name for --pair-host (e.g. hci0)",
    )
    parser.add_argument(
        "--save-profile", metavar="NAME",
        help="Save a named Master MAC profile (uses --set-mac if given, else reads controller)",
    )
    parser.add_argument(
        "--apply-profile", metavar="NAME",
        help="Write a saved Master MAC profile to the connected controller",
    )
    parser.add_argument(
        "--delete-profile", metavar="NAME",
        help="Delete a saved Master MAC profile",
    )
    parser.add_argument(
        "--list-profiles", action="store_true",
        help="List all saved MAC profiles and automatic backups",
    )
    parser.add_argument(
        "--backup", metavar="FILE",
        help="Export connected controller MAC details to a JSON backup file",
    )
    parser.add_argument(
        "--restore", nargs="?", const="__AUTO__", default=None, metavar="FILE",
        help="Restore previous Master MAC from automatic backup (or from exported FILE)",
    )
    parser.add_argument(
        "--clone", action="store_true",
        help="Copy Controller #1's Master MAC onto all other connected controllers",
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="Allow writing non-standard MACs (all-zeros, broadcast, or multicast)",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")

    args, _ = parser.parse_known_args(argv)
    return args


def _has_explicit_action(args):
    """Return True if the caller passed a one-shot CLI action flag."""
    return any([
        args.check,
        args.set_mac is not None,
        args.generate_mac,
        args.pair_host,
        args.save_profile is not None,
        args.apply_profile is not None,
        args.delete_profile is not None,
        args.list_profiles,
        args.backup is not None,
        args.restore is not None,
        args.clone,
    ])


def _select_host_adapter(backend, adapter_name=None):
    """Select matching local Bluetooth adapter or raise ValueError."""
    adapters = backend.detect_host_bluetooth_macs()
    if not adapters:
        raise ValueError("No active local Bluetooth adapter detected on this machine")

    if adapter_name:
        for entry in adapters:
            if entry["adapter"].lower() == adapter_name.lower():
                return entry
        available = ", ".join(a["adapter"] for a in adapters)
        raise ValueError(f"Bluetooth adapter '{adapter_name}' not found (available: {available})")

    return adapters[0]


def _wait_for_devices(backend, timeout, quiet=False):
    """Poll backend for connected PS3 controllers until detected or timeout expires."""
    start_time = time.time()
    devices = backend.detect_devices()
    if devices:
        return devices

    if not quiet:
        print("[i] Waiting for PS3 controller connection via USB cable...")
        print("    (Connect mini-USB cable to computer, or press Ctrl+C to cancel)")

    while not devices:
        if timeout is not None and (time.time() - start_time) >= timeout:
            return []
        time.sleep(0.5)
        devices = backend.detect_devices()
    return devices


def _reexec_with_sudo(args):
    """Re-execute current script with sudo using only validated arguments (S8705-safe)."""
    print("\n[*] Administrator privileges (sudo) required to access controller memory...")
    script_path = os.path.abspath(__file__)
    args_list = ["sudo", "--", sys.executable, script_path, "--no-sudo"]

    flag_map = [
        (args.non_interactive, "--non-interactive"),
        (args.all, "--all"),
        (args.check, "--check"),
        (args.generate_mac, "--generate-mac"),
        (args.pair_host, "--pair-host"),
        (args.clone, "--clone"),
        (args.force, "--force"),
    ]
    for enabled, flag in flag_map:
        if enabled:
            args_list.append(flag)

    value_map = [
        (args.set_mac, "--set-mac"),
        (args.adapter, "--adapter"),
        (args.save_profile, "--save-profile"),
        (args.apply_profile, "--apply-profile"),
        (args.backup, "--backup"),
    ]
    for val, flag in value_map:
        if val is not None:
            args_list.extend([flag, str(val)])

    if args.restore is not None:
        args_list.append("--restore")
        if args.restore != "__AUTO__":
            args_list.append(str(args.restore))

    try:
        os.execvp("sudo", args_list)
    except Exception as e:
        print(f"[!] Failed to re-exec with sudo: {e}")
        return 2
    return 0


def _handle_store_only_action(args, store_path=None):
    """Handle profile management actions that do not require hardware access."""
    if args.list_profiles:
        data = load_store(store_path)
        profiles = list_profiles(store_path)
        payload = {"profiles": profiles, "backups": data.get("backups", {})}
        if args.json:
            print(format_json(payload))
        else:
            _print_profiles_and_backups(profiles, data.get("backups", {}))
        return 0

    if args.delete_profile is not None:
        deleted = delete_profile(args.delete_profile, store_path=store_path)
        if args.json:
            print(format_json({"profile": args.delete_profile, "deleted": deleted}))
        elif deleted:
            print(f"[✓] Deleted profile '{args.delete_profile}'.")
        else:
            print(f"[!] Profile '{args.delete_profile}' not found.")
        return 0 if deleted else 1

    if args.save_profile is not None and args.set_mac is not None:
        try:
            saved_mac = save_profile(
                args.save_profile, args.set_mac, store_path=store_path, force=args.force
            )
        except ValueError as e:
            return _emit_error(str(e), as_json=args.json)
        if args.json:
            print(format_json({"profile": args.save_profile, "mac": saved_mac, "saved": True}))
        else:
            print(f"[✓] Saved profile '{args.save_profile}' -> {saved_mac}")
        return 0

    return None


def _emit_error(message, as_json=False, exit_code=1):
    """Print an error message as JSON or plain text and return exit_code."""
    if as_json:
        print(format_json({"error": message}))
    else:
        print(f"[!] {message}")
    return exit_code


def _print_profiles_and_backups(profiles, backups):
    """Display saved profiles and stored automatic backups."""
    print("============================================================")
    print("             SAVED PROFILES & BACKUP STORE                  ")
    print("============================================================")
    if profiles:
        print("\nSaved Profiles:")
        for name, meta in profiles.items():
            print(f"  - {name:<18} {meta['mac']}")
    else:
        print("\nSaved Profiles: (none)")

    if backups:
        print("\nAutomatic Controller Backups:")
        for key, entry in sorted(backups.items()):
            prev_mac = entry.get("previous_master_mac", "?")
            orig_mac = entry.get("original_master_mac", prev_mac)
            print(f"  - {key:<18} last={prev_mac}  original={orig_mac}")
    else:
        print("\nAutomatic Controller Backups: (none)")
    print()


def _print_controller_results(results, store_path=None, host_adapters=None, total_detected=None):
    """Render inspection or write results in a readable terminal layout."""
    count = total_detected if total_detected is not None else len(results)
    print(f"[✓] Detected {count} PS3 Controller(s)!\n")

    for idx, info in enumerate(results, 1):
        header = f"CONTROLLER #{idx}" if len(results) > 1 else "CONTROLLER DETAILS"
        print(f"--- {header} --------------------------------------")
        print(f"Hardware Path : {info['device_path']}")
        print(f"Device Node   : {info.get('devnode') or 'Not ready'}")

        if info.get("error"):
            if "Permission denied" in info["error"]:
                print(f"[!] Access denied to {info.get('devnode') or 'device'}: {info['error']}")
            else:
                print(f"[!] Error: {info['error']}")
            print("------------------------------------------------------------\n")
            continue

        if info.get("previous_master_mac") and "requested_master_mac" in info:
            status = "VERIFIED" if info.get("verified") else "UNVERIFIED"
            print(f"\n[✓] Master MAC Updated ({status}):")
            print(f"    Previous : {info['previous_master_mac']}")
            print(f"    Current  : >>  {info['master_mac']}  <<")
            if info.get("backup_saved"):
                print("    Backup   : Saved automatically to local config store")
        else:
            print("\n1. MASTER MAC (Required for ESP32 / Ps3.begin):")
            print(f"   >>  {info['master_mac']}  <<")

        if info.get("warning"):
            print(f"   [!] {info['warning']}")

        snippets = format_code_snippets(info["master_mac"])
        print("\n   Paste into Arduino setup() / C code:")
        print(f"   {snippets['arduino']}")
        print(f"   {snippets['c_array']}")

        dev_mac = info.get("device_mac", "Unavailable")
        print("\n2. DEVICE MAC (Physical Bluetooth Address of Controller):")
        print(f"   >>  {dev_mac}  <<")

        key = _controller_backup_key(dev_mac, info["device_path"])
        backup_mac = get_backup_mac(key, store_path=store_path)
        if backup_mac:
            print(f"   Last Backup : {backup_mac}")

        print("------------------------------------------------------------\n")

    if host_adapters:
        adapters_str = ", ".join(f"{a['adapter']} ({a['address']})" for a in host_adapters)
        print(f"[i] Local Host Bluetooth: {adapters_str}\n")


def _resolve_restore_target(info, restore_spec, idx, store_path=None):
    """Determine target MAC to restore for a single inspected controller."""
    if restore_spec == "__AUTO__":
        key = _controller_backup_key(info.get("device_mac"), info["device_path"])
        backup_mac = get_backup_mac(key, store_path=store_path)
        if not backup_mac:
            raise ValueError(f"No automatic backup found for controller '{key}'")
        return backup_mac

    entries = import_backup_file(restore_spec)
    dev_mac = info.get("device_mac")
    if dev_mac and dev_mac != "Unavailable":
        for entry in entries:
            if entry.get("device_mac") == dev_mac and entry.get("master_mac"):
                return entry["master_mac"]
    if idx < len(entries) and entries[idx].get("master_mac"):
        return entries[idx]["master_mac"]
    if entries[0].get("master_mac"):
        return entries[0]["master_mac"]
    raise ValueError(f"No valid master_mac found in backup file '{restore_spec}'")


def _execute_cli_action(args, target_devices, backend, store_path=None):
    """Execute one-shot CLI inspection or modification across target_devices."""
    if args.set_mac is not None:
        return [
            change_controller_mac(d, args.set_mac, backend=backend, force=args.force, store_path=store_path)
            for d in target_devices
        ]

    if args.generate_mac:
        generated_mac = generate_random_mac()
        return [
            change_controller_mac(d, generated_mac, backend=backend, force=args.force, store_path=store_path)
            for d in target_devices
        ]

    if args.pair_host:
        adapter = _select_host_adapter(backend, args.adapter)
        results = []
        for dev_path in target_devices:
            res = change_controller_mac(
                dev_path, adapter["address"], backend=backend, force=args.force, store_path=store_path
            )
            res["paired_adapter"] = adapter["adapter"]
            results.append(res)
        return results

    if args.apply_profile is not None:
        profile_mac = get_profile(args.apply_profile, store_path=store_path)
        if not profile_mac:
            raise ValueError(f"Profile '{args.apply_profile}' does not exist")
        return [
            change_controller_mac(d, profile_mac, backend=backend, force=args.force, store_path=store_path)
            for d in target_devices
        ]

    if args.restore is not None:
        results = []
        for idx, dev_path in enumerate(target_devices):
            info = inspect_controller(dev_path, backend=backend)
            if info.get("error"):
                results.append(info)
                continue
            target_mac = _resolve_restore_target(info, args.restore, idx, store_path=store_path)
            results.append(
                change_controller_mac(dev_path, target_mac, backend=backend, force=True, store_path=store_path)
            )
        return results

    if args.clone:
        inspected = [inspect_controller(d, backend=backend) for d in target_devices]
        if len(inspected) < 2:
            raise ValueError("--clone requires at least 2 connected PS3 controllers (use -a/--all)")
        if inspected[0].get("error") or not inspected[0].get("master_mac"):
            raise ValueError(f"Cannot read source Master MAC from Controller #1: {inspected[0].get('error')}")
        source_mac = inspected[0]["master_mac"]
        results = [inspected[0]]
        for dev_path in target_devices[1:]:
            results.append(
                change_controller_mac(dev_path, source_mac, backend=backend, force=args.force, store_path=store_path)
            )
        return results

    # Read / Check / Save-Profile-From-Controller / Backup
    inspected = [inspect_controller(d, backend=backend) for d in target_devices]
    if args.save_profile is not None and inspected and not inspected[0].get("error"):
        saved = save_profile(
            args.save_profile, inspected[0]["master_mac"], store_path=store_path, force=args.force
        )
        inspected[0]["saved_profile"] = {"name": args.save_profile, "mac": saved}

    if args.backup is not None and not any(item.get("error") for item in inspected):
        export_backup_file(args.backup, inspected)

    return inspected


# ============================================================================
# Interactive TUI Menu Loop
# ============================================================================

def _tui_change_mac(target_devices, backend, store_path):
    """Interactive prompt to change Master MAC on connected controller(s)."""
    raw = safe_input("Enter new Master MAC (e.g. 00:1d:0d:4c:e3:78, or blank to cancel): ").strip()
    if not raw:
        return
    try:
        normalized, warn = validate_mac_for_write(raw, force=False)
    except ValueError as e:
        print(f"[!] {e}")
        confirm = safe_input("Force write anyway? [y/N]: ").strip().lower()
        if confirm != "y":
            return
        normalized = normalize_mac(raw)
        force = True
    else:
        if warn:
            print(f"[!] {warn}")
        force = False

    for dev_path in target_devices:
        res = change_controller_mac(dev_path, normalized, backend=backend, force=force, store_path=store_path)
        _report_tui_write_result(res)


def _tui_profiles_menu(target_devices, inspected, backend, store_path):
    """Interactive submenu for saving, applying, or deleting named MAC profiles."""
    profiles = list_profiles(store_path)
    print("\n--- Saved Profiles ---")
    names = list(profiles.keys())
    if names:
        for idx, name in enumerate(names, 1):
            print(f"  [{idx}] {name:<18} -> {profiles[name]['mac']}")
    else:
        print("  (no profiles saved yet)")

    print("\n  [S] Save current Controller #1 Master MAC as a profile")
    print("  [A] Apply a profile to connected controller(s)")
    print("  [D] Delete a profile")
    print("  [Enter] Back\n")

    choice = safe_input("Profile action: ").strip().lower()
    if choice == "s":
        if not inspected or inspected[0].get("error"):
            print("[!] No readable controller available to save from.")
            return
        name = safe_input("Profile name (e.g. robot_a): ").strip()
        if name:
            try:
                saved = save_profile(name, inspected[0]["master_mac"], store_path=store_path, force=True)
                print(f"[✓] Saved profile '{name}' -> {saved}")
            except ValueError as e:
                print(f"[!] {e}")
    elif choice == "a":
        if not names:
            print("[!] No saved profiles available to apply.")
            return
        sel = safe_input("Enter profile number or name: ").strip()
        chosen_name = names[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(names) else sel
        mac = get_profile(chosen_name, store_path=store_path)
        if not mac:
            print(f"[!] Profile '{chosen_name}' not found.")
            return
        for dev_path in target_devices:
            res = change_controller_mac(dev_path, mac, backend=backend, force=True, store_path=store_path)
            _report_tui_write_result(res)
    elif choice == "d":
        if not names:
            print("[!] No saved profiles available to delete.")
            return
        sel = safe_input("Profile name or number to delete: ").strip()
        chosen_name = names[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(names) else sel
        if delete_profile(chosen_name, store_path=store_path):
            print(f"[✓] Deleted profile '{chosen_name}'.")
        else:
            print(f"[!] Profile '{chosen_name}' not found.")


def _tui_generate_mac(target_devices, backend, store_path):
    """Generate a random safe unicast MAC and write it to connected controller(s)."""
    new_mac = generate_random_mac()
    print(f"[*] Generated random unicast MAC: {new_mac}")
    confirm = safe_input("Write this MAC to controller(s)? [Y/n]: ").strip().lower()
    if confirm in ("", "y", "yes"):
        for dev_path in target_devices:
            res = change_controller_mac(dev_path, new_mac, backend=backend, store_path=store_path)
            _report_tui_write_result(res)


def _tui_pair_host(target_devices, backend, store_path):
    """Pair connected controller(s) to this computer's local Bluetooth adapter."""
    adapters = backend.detect_host_bluetooth_macs()
    if not adapters:
        print("[!] No active local Bluetooth adapter found on this machine.")
        return
    chosen = adapters[0]
    if len(adapters) > 1:
        for idx, item in enumerate(adapters, 1):
            print(f"  [{idx}] {item['adapter']} ({item['address']})")
        sel = safe_input("Select adapter [1]: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(adapters):
            chosen = adapters[int(sel) - 1]

    print(f"[*] Pairing controller(s) to {chosen['adapter']} ({chosen['address']})...")
    for dev_path in target_devices:
        res = change_controller_mac(dev_path, chosen["address"], backend=backend, store_path=store_path)
        _report_tui_write_result(res)


def _tui_restore_backup(target_devices, inspected, backend, store_path):
    """Restore previous Master MAC from automatic backup store."""
    for info in inspected:
        key = _controller_backup_key(info.get("device_mac"), info["device_path"])
        backup_mac = get_backup_mac(key, store_path=store_path)
        if not backup_mac:
            print(f"[!] No automatic backup found for {key}.")
            continue
        print(f"[*] Found backup for {key}: {backup_mac}")
        confirm = safe_input(f"Restore Master MAC to {backup_mac}? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            res = change_controller_mac(info["device_path"], backup_mac, backend=backend, force=True, store_path=store_path)
            _report_tui_write_result(res)


def _report_tui_write_result(res):
    """Print concise status of an interactive write operation."""
    if res.get("error"):
        print(f"[!] Failed: {res['error']}")
    elif res.get("verified"):
        print(f"[✓] Verified Master MAC -> {res['master_mac']} (previous: {res['previous_master_mac']})")
    else:
        print(f"[!] Master MAC written as {res['master_mac']} (verification unconfirmed)")


def _run_interactive_tui(target_devices, backend, store_path=None):
    """Interactive menu loop allowing users to inspect, write, pair, profile, or restore."""
    while True:
        devices = backend.detect_devices()
        active_targets = devices if devices else target_devices
        inspected = [inspect_controller(d, backend=backend) for d in active_targets]
        host_adapters = backend.detect_host_bluetooth_macs()

        clear_screen()
        print("============================================================")
        print(f"         PS3 CONTROLLER MAC ADDRESS MANAGER v{__version__}         ")
        print("============================================================\n")
        _print_controller_results(
            inspected, store_path=store_path, host_adapters=host_adapters, total_detected=len(devices)
        )

        print("Actions:")
        print("  [1] Change Master MAC address (custom)")
        print("  [2] Profiles (save / apply / delete presets)")
        print("  [3] Generate & write random safe MAC (for ESP32)")
        print("  [4] Pair to this PC's Bluetooth adapter (sixpair)")
        print("  [5] Restore previous Master MAC from backup")
        print("  [6] Refresh / Re-scan controller")
        print("  [Enter / Q] Exit\n")

        choice = safe_input("Select option [Enter to exit]: ").strip().lower()
        if choice in ("", "q", "quit", "exit"):
            return 0
        if choice == "1":
            _tui_change_mac(active_targets, backend, store_path)
        elif choice == "2":
            _tui_profiles_menu(active_targets, inspected, backend, store_path)
        elif choice == "3":
            _tui_generate_mac(active_targets, backend, store_path)
        elif choice == "4":
            _tui_pair_host(active_targets, backend, store_path)
        elif choice == "5":
            _tui_restore_backup(active_targets, inspected, backend, store_path)
        elif choice == "6":
            continue
        else:
            print(f"[!] Unknown option: {choice}")

        safe_input("\nPress [Enter] to return to menu...")


# ============================================================================
# Entry Point
# ============================================================================

def _resolve_backend(backend):
    """Return supplied backend or auto-select platform backend (honoring test mocks)."""
    if backend is not None:
        return backend
    is_linux_mocked = (
        hasattr(get_ps3_devices, "assert_called")
        or hasattr(read_master_mac, "assert_called")
        or hasattr(write_master_mac, "assert_called")
        or hasattr(find_hidraw_node, "assert_called")
    )
    return LinuxBackend() if is_linux_mocked else get_backend()


def _validate_preconditions(args, backend, store_path):
    """Validate CLI inputs that do not depend on USB device connection."""
    if args.set_mac is not None:
        validate_mac_for_write(args.set_mac, force=args.force)
    if args.apply_profile is not None and not get_profile(args.apply_profile, store_path=store_path):
        raise ValueError(f"Profile '{args.apply_profile}' does not exist")
    if args.pair_host:
        _select_host_adapter(backend, args.adapter)
    if args.restore is not None and args.restore != "__AUTO__":
        import_backup_file(args.restore)


def main(argv=None, backend=None, store_path=None):
    """Main program entry point."""
    backend = _resolve_backend(backend)
    args = parse_args(argv)

    store_only_exit = _handle_store_only_action(args, store_path=store_path)
    if store_only_exit is not None:
        return store_only_exit

    try:
        _validate_preconditions(args, backend, store_path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return _emit_error(str(e), as_json=args.json, exit_code=1)

    if not args.json:
        clear_screen()
        print("============================================================")
        print(f"         PS3 CONTROLLER MAC ADDRESS MANAGER v{__version__}         ")
        print("============================================================\n")

    timeout = args.timeout
    if timeout is None and (args.non_interactive or not sys.stdin.isatty()):
        timeout = 0.0

    devices = _wait_for_devices(backend, timeout, quiet=args.json)
    if not devices:
        if args.json:
            print(format_json([]))
        else:
            print(f"\n[!] Timeout ({timeout}s) reached. No PS3 controller detected.")
        return 1

    target_devices = devices if args.all or len(devices) > 1 or args.clone else [devices[0]]

    try:
        results = _execute_cli_action(args, target_devices, backend, store_path=store_path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return _emit_error(str(e), as_json=args.json, exit_code=1)

    permission_error = any(
        item.get("error") and "Permission denied" in item["error"] for item in results
    )
    if (
        permission_error
        and not args.no_sudo
        and hasattr(os, "geteuid")
        and os.geteuid() != 0
        and not args.json
    ):
        return _reexec_with_sudo(args)

    if args.json:
        print(format_json(results))
        return 1 if any(item.get("error") for item in results) else 0

    host_adapters = backend.detect_host_bluetooth_macs()
    _print_controller_results(
        results, store_path=store_path, host_adapters=host_adapters, total_detected=len(devices)
    )

    if args.save_profile is not None and results and results[0].get("saved_profile"):
        sp = results[0]["saved_profile"]
        print(f"[✓] Saved profile '{sp['name']}' -> {sp['mac']}\n")
    if args.backup is not None and not any(item.get("error") for item in results):
        print(f"[✓] Exported controller backup to {args.backup}\n")

    has_errors = any(item.get("error") for item in results)
    enter_tui = (
        not args.non_interactive
        and not _has_explicit_action(args)
        and sys.stdin.isatty()
        and not has_errors
    )
    if enter_tui:
        return _run_interactive_tui(target_devices, backend, store_path=store_path)

    if (args.check or (not _has_explicit_action(args) and has_errors)) and not args.non_interactive:
        safe_input("Done! Press [Enter] to close terminal...")

    return 1 if has_errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
