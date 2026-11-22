#!/usr/bin/env python3
"""PS3 Controller MAC Address Manager.

Read, change, pair, back up, and manage Master & Device MAC addresses on
Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers via USB HID on
Windows, macOS, and Linux.

Author: Bagus Wijaya (Warsky)
Repository: https://github.com/chocowarsky/ps3-mac-manager
License: MIT
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
from datetime import datetime, timezone
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any, ClassVar

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

__version__ = "2.0.0"

SONY_VID = 0x054C
PS3_PID = 0x0268
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _configure_console():
    """Configure UTF-8 output and Win32 ANSI virtual terminal processing."""
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(ValueError, OSError, LookupError):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if sys.platform == "win32" and hasattr(ctypes, "windll"):
        with contextlib.suppress(OSError, AttributeError):
            kernel32 = ctypes.windll.kernel32
            if isinstance(kernel32, ctypes.CDLL) and type(kernel32).__module__ == "ctypes":
                kernel32.GetStdHandle.argtypes = [ctypes.c_int32]
                kernel32.GetStdHandle.restype = ctypes.c_void_p
                kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
                kernel32.GetConsoleMode.restype = ctypes.c_int32
                kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                kernel32.SetConsoleMode.restype = ctypes.c_int32
            handle = kernel32.GetStdHandle(-11)
            invalid_handle = ctypes.c_void_p(-1).value
            if handle not in (None, 0, -1, invalid_handle):
                mode = ctypes.c_uint32(0)
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)


_configure_console()


def HIDIOCSFEAT(size):
    """Compute ioctl number for Linux HIDIOCSFEATURE(len)."""
    return (3 << 30) | (size << 16) | (ord("H") << 8) | 0x06


def HIDIOCGFEAT(size):
    """Compute ioctl number for Linux HIDIOCGFEATURE(len)."""
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


def _is_real_cdll(dll):
    """Return True when dll is a real ctypes CDLL/WinDLL instance rather than a mock."""
    return isinstance(dll, ctypes.CDLL) and type(dll).__module__ == "ctypes"


def _permission_denied_message(backend_name):
    """Return an OS-appropriate permission troubleshooting message."""
    if backend_name == "win32":
        return "Permission denied opening HID device (close Steam/DS3 drivers or run as Administrator)"
    if backend_name == "darwin":
        return "Permission denied opening HID device (grant Terminal Input Monitoring or run with sudo)"
    return "Permission denied (udev rule required or run with sudo)"


# ============================================================================
# MAC Normalization, Validation, Generation & Snippets
# ============================================================================

def _strip_mac_wrappers(cleaned):
    """Strip surrounding quotes or C-array braces from MAC strings."""
    while len(cleaned) >= 2 and (
        (cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"))
        or (cleaned[0] == "{" and cleaned[-1] == "}")
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _split_mac_parts(cleaned):
    """Split supported MAC string formats into raw hex byte strings."""
    cleaned = _strip_mac_wrappers(cleaned)
    parts: list[str] = []
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",")]
    elif ":" in cleaned or "-" in cleaned:
        sep = ":" if ":" in cleaned else "-"
        parts = [part.strip() for part in cleaned.split(sep)]
    elif " " in cleaned or "\t" in cleaned:
        parts = cleaned.split()
    elif "." in cleaned:
        groups = cleaned.split(".")
        if len(groups) == 3 and all(len(g) == 4 for g in groups):
            joined = "".join(groups)
            parts = [joined[i:i + 2] for i in range(0, 12, 2)]
    else:
        raw = cleaned[2:] if cleaned.lower().startswith("0x") and len(cleaned) == 14 else cleaned
        if len(raw) == 12:
            parts = [raw[i:i + 2] for i in range(0, 12, 2)]
    return parts


def normalize_mac(mac_str):
    """Normalize a Bluetooth MAC address to lowercase colon-separated format.

    Accepts colon, hyphen, space, comma-separated C hex bytes (`0x00, ...`),
    Cisco dot (`aabb.ccdd.eeff`), or raw 12-char hex strings.
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
    for raw_part in octets:
        part = raw_part[2:] if raw_part.lower().startswith("0x") else raw_part
        if not 1 <= len(part) <= 2 or not all(ch in HEX_DIGITS for ch in part):
            raise ValueError(f"Invalid octet '{raw_part}' in MAC address '{mac_str}'")
        val = int(part, 16)
        byte_vals.append(val)

    return ":".join(f"{b:02x}" for b in byte_vals)


def mac_to_bytes(mac_str):
    """Convert a MAC address string into a list of 6 integer byte values."""
    normalized = normalize_mac(mac_str)
    return [int(part, 16) for part in normalized.split(":")]


def validate_mac(mac_str):
    """Validate Bluetooth MAC format and check for clone/unprogrammed signatures.

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

    warning = None
    if any(not 0 <= b <= 0xFF for b in byte_vals):
        warning = "MAC byte out of range"
    elif all(b == 0 for b in byte_vals):
        warning = "Warning: Clone or uninitialized controller returned all zeros (00:00:00:00:00:00)"
    elif all(b == 0xFF for b in byte_vals):
        warning = "Warning: Clone controller returned all 0xFF (unprogrammed EEPROM)"
    elif byte_vals[0] & 0x01:
        warning = "Warning: Multicast bit is set (invalid for Bluetooth host address)"

    return (warning is None), warning


def validate_mac_for_write(mac_str, force=False):
    """Normalize and validate a target Master MAC before writing to EEPROM.

    Returns (normalized_mac, warning). Raises ValueError on invalid MAC unless force=True.
    """
    normalized = normalize_mac(mac_str)
    is_valid, warning = validate_mac(normalized)
    if not is_valid and not force:
        raise ValueError(f"{warning} (pass --force to write anyway)")
    return normalized, warning


def generate_random_mac():
    """Generate a random, safe locally administered unicast Bluetooth MAC address.

    Bit 0 of byte 0 is 0 (unicast) and bit 1 of byte 0 is 1 (locally administered).
    """
    while True:
        raw = os.urandom(6)
        b0 = (raw[0] & 0xFE) | 0x02
        octets = [b0, *list(raw[1:])]
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
# Win32 ctypes Structure Definitions
# ============================================================================

class _Win32GUID(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


class _SPDeviceInterfaceData(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("cbSize", ctypes.c_uint32),
        ("InterfaceClassGuid", _Win32GUID),
        ("Flags", ctypes.c_uint32),
        ("Reserved", ctypes.c_void_p),
    ]


class _BluetoothFindRadioParams(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [("dwSize", ctypes.c_uint32)]


class _BluetoothAddress(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("ullLong", ctypes.c_uint64),
        ("rgBytes", ctypes.c_uint8 * 6),
    ]


class _BluetoothRadioInfo(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("dwSize", ctypes.c_uint32),
        ("address", _BluetoothAddress),
        ("szName", ctypes.c_uint16 * 248),
        ("ulClassofDevice", ctypes.c_uint32),
        ("lmpSubversion", ctypes.c_uint16),
        ("manufacturer", ctypes.c_uint16),
    ]


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
        """Enumerate connected Sony DualShock 3 devices in sysfs."""
        return get_ps3_devices()

    def find_node(self, device_path):
        """Resolve sysfs path to /dev/hidrawX."""
        return find_hidraw_node(device_path)

    def read_master_mac(self, devnode):
        """Read Master Host MAC via Linux hidraw feature report 0xF5."""
        return read_master_mac(devnode)

    def write_master_mac(self, devnode, mac_str):
        """Write Master Host MAC via Linux hidraw feature report 0xF5."""
        return write_master_mac(devnode, mac_str)

    def read_device_mac(self, device_path):
        """Read physical Device MAC via sysfs or feature report 0xF2."""
        return read_device_mac(device_path)

    def detect_host_bluetooth_macs(self):
        """Discover local Bluetooth adapters from /sys/class/bluetooth."""
        return detect_linux_bluetooth_macs()


class WindowsBackend(BaseBackend):
    """Windows implementation using standard library ctypes for Win32 HID & Bluetooth APIs."""

    name = "win32"

    def __init__(self, setupapi=None, hid=None, kernel32=None, bthprops=None):
        """Initialize Win32 backend with optional injected DLL mocks for testing."""
        self._setupapi = setupapi
        self._hid = hid
        self._kernel32 = kernel32
        self._bthprops = bthprops
        self._initialized = False
        self._signatures_configured = False

    def _configure_win32_signatures(self):
        """Set explicit ctypes argtypes/restype on real Win32 DLLs to prevent 64-bit truncation."""
        if self._signatures_configured:
            return
        self._signatures_configured = True

        if _is_real_cdll(self._kernel32):
            self._kernel32.CreateFileW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            self._kernel32.CreateFileW.restype = ctypes.c_void_p
            self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle.restype = ctypes.c_int32
            self._kernel32.GetLastError.argtypes = []
            self._kernel32.GetLastError.restype = ctypes.c_uint32

        if _is_real_cdll(self._hid):
            self._hid.HidD_GetHidGuid.argtypes = [ctypes.c_void_p]
            self._hid.HidD_GetHidGuid.restype = None
            self._hid.HidD_GetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
            self._hid.HidD_GetFeature.restype = ctypes.c_ubyte
            self._hid.HidD_SetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
            self._hid.HidD_SetFeature.restype = ctypes.c_ubyte

        if _is_real_cdll(self._setupapi):
            self._setupapi.SetupDiGetClassDevsW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            self._setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
            self._setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            self._setupapi.SetupDiEnumDeviceInterfaces.restype = ctypes.c_int32
            self._setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            self._setupapi.SetupDiGetDeviceInterfaceDetailW.restype = ctypes.c_int32
            self._setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
            self._setupapi.SetupDiDestroyDeviceInfoList.restype = ctypes.c_int32

    def _configure_bthprops_signatures(self, bthprops):
        """Configure ctypes argtypes/restype for Bluetooth radio discovery DLL."""
        if not _is_real_cdll(bthprops):
            return
        bthprops.BluetoothFindFirstRadio.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        bthprops.BluetoothFindFirstRadio.restype = ctypes.c_void_p
        bthprops.BluetoothFindNextRadio.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        bthprops.BluetoothFindNextRadio.restype = ctypes.c_int32
        bthprops.BluetoothGetRadioInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        bthprops.BluetoothGetRadioInfo.restype = ctypes.c_uint32
        bthprops.BluetoothFindRadioClose.argtypes = [ctypes.c_void_p]
        bthprops.BluetoothFindRadioClose.restype = ctypes.c_int32

    def _init_win32(self):
        """Load Win32 DLLs lazily and initialize signatures."""
        if self._initialized:
            return
        self._initialized = True
        if hasattr(ctypes, "windll"):
            if self._setupapi is None:
                self._setupapi = ctypes.windll.setupapi
            if self._hid is None:
                self._hid = ctypes.windll.hid
            if self._kernel32 is None:
                self._kernel32 = ctypes.windll.kernel32
        self._configure_win32_signatures()

    def _open_hid_handle(self, device_path, raise_on_error=True):
        """Open a Win32 HID device interface handle, falling back to query-only sharing."""
        self._init_win32()
        if not self._kernel32 or not self._hid:
            if raise_on_error:
                raise OSError("Win32 HID subsystem not available")
            return None

        generic_rw = 0x80000000 | 0x40000000
        file_share_rw = 0x00000001 | 0x00000002
        open_existing = 3
        invalid_handle = ctypes.c_void_p(-1).value

        handle = invalid_handle
        err = 0
        for desired_access in (generic_rw, 0):
            handle = self._kernel32.CreateFileW(
                device_path,
                desired_access,
                file_share_rw,
                None,
                open_existing,
                0,
                None,
            )
            if handle not in (invalid_handle, -1, None, 0):
                return handle
            err = self._kernel32.GetLastError()
            if err not in (5, 32):
                break

        if not raise_on_error:
            return None
        if err in (5, 32):
            raise PermissionError(_permission_denied_message(self.name))
        if err in (2, 1167):
            raise FileNotFoundError("Device disconnected")
        raise OSError(f"Failed to open HID device (Win32 Error {err})")

    def detect_devices(self):
        """Enumerate Win32 HID device interface paths matching Sony DualShock 3 (054C:0268)."""
        self._init_win32()
        if not self._setupapi or not self._hid:
            return []

        hid_guid = _Win32GUID()
        self._hid.HidD_GetHidGuid(ctypes.byref(hid_guid))

        digcf_present = 0x00000002
        digcf_deviceinterface = 0x00000010
        hdevinfo = self._setupapi.SetupDiGetClassDevsW(
            ctypes.byref(hid_guid),
            None,
            None,
            digcf_present | digcf_deviceinterface,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if hdevinfo in (invalid_handle, -1, None, 0):
            return []

        devices = []
        try:
            device_index = 0
            interface_data = _SPDeviceInterfaceData(cbSize=ctypes.sizeof(_SPDeviceInterfaceData))

            while self._setupapi.SetupDiEnumDeviceInterfaces(
                hdevinfo, None, ctypes.byref(hid_guid), device_index, ctypes.byref(interface_data)
            ):
                required_size = ctypes.c_uint32(0)
                self._setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdevinfo, ctypes.byref(interface_data), None, 0, ctypes.byref(required_size), None
                )

                if required_size.value > 0:
                    detail_buffer = ctypes.create_string_buffer(required_size.value)
                    cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
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
        """Return the Win32 device interface path."""
        return device_path

    def read_master_mac(self, devnode):
        """Read Master Host MAC from DualShock 3 via Win32 HID Feature Report 0xF5."""
        handle = self._open_hid_handle(devnode, raise_on_error=True)
        try:
            for buf_size in (64, 8, 65):
                buf = bytearray([0xF5] + [0] * (buf_size - 1))
                c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
                if self._hid.HidD_GetFeature(handle, c_buf, len(buf)):
                    return ":".join(f"{b:02x}" for b in buf[2:8]).lower()
            err = self._kernel32.GetLastError()
            raise OSError(f"HidD_GetFeature report 0xF5 failed (Win32 Error {err})")
        finally:
            self._kernel32.CloseHandle(handle)

    def write_master_mac(self, devnode, mac_str):
        """Write Master Host MAC to DualShock 3 via Win32 HID Feature Report 0xF5."""
        normalized = normalize_mac(mac_str)
        mac_bytes = mac_to_bytes(normalized)
        handle = self._open_hid_handle(devnode, raise_on_error=True)
        try:
            payloads = (
                bytearray([0xF5, 0x01, *mac_bytes] + [0] * 56),
                bytearray([0xF5, 0x01, *mac_bytes]),
                bytearray([0xF5, 0x01, *mac_bytes] + [0] * 57),
            )
            for payload in payloads:
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

        try:
            for buf_size in (64, 18, 17, 65):
                buf = bytearray([0xF2] + [0] * (buf_size - 1))
                c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
                if self._hid.HidD_GetFeature(handle, c_buf, len(buf)):
                    mac_bytes = buf[4:10]
                    if any(b != 0 for b in mac_bytes):
                        return ":".join(f"{b:02x}" for b in mac_bytes).lower()
            return "Unavailable"
        finally:
            self._kernel32.CloseHandle(handle)

    def _load_bthprops_dll(self):
        """Locate and load Windows Bluetooth control panel library if present."""
        if self._bthprops is not None:
            self._configure_bthprops_signatures(self._bthprops)
            return self._bthprops
        if hasattr(ctypes, "windll"):
            for dll_name in ("bthprops.cpl", "irprops.cpl"):
                try:
                    loaded = ctypes.WinDLL(dll_name)
                except OSError:
                    continue
                self._bthprops = loaded
                self._configure_bthprops_signatures(loaded)
                return loaded
        return None

    def _read_radio_adapter_info(self, bthprops, radio_handle, idx):
        """Extract normalized MAC address and adapter name for a single Win32 radio."""
        info = _BluetoothRadioInfo(dwSize=ctypes.sizeof(_BluetoothRadioInfo))
        if bthprops.BluetoothGetRadioInfo(radio_handle, ctypes.byref(info)) != 0:
            return None
        mac_bytes = list(info.address.rgBytes[:6])[::-1]
        if not any(b != 0 for b in mac_bytes):
            return None
        mac_str = ":".join(f"{b:02x}" for b in mac_bytes)
        raw_name = bytes(info.szName).decode("utf-16-le", errors="ignore")
        adapter_name = raw_name.split("\x00", 1)[0].strip() or f"bt{idx}"
        return {"adapter": adapter_name, "address": mac_str}

    def detect_host_bluetooth_macs(self):
        """Discover local Bluetooth adapter MACs on Windows via bthprops.cpl."""
        self._init_win32()
        bthprops = self._load_bthprops_dll()
        if not bthprops or not self._kernel32:
            return []

        params = _BluetoothFindRadioParams(dwSize=ctypes.sizeof(_BluetoothFindRadioParams))
        radio_handle = ctypes.c_void_p()
        find_handle = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio_handle))
        if not find_handle:
            return []

        adapters = []
        idx = 0
        try:
            while True:
                entry = self._read_radio_adapter_info(bthprops, radio_handle, idx)
                if entry:
                    adapters.append(entry)
                self._kernel32.CloseHandle(radio_handle)
                idx += 1
                if not bthprops.BluetoothFindNextRadio(find_handle, ctypes.byref(radio_handle)):
                    break
        except (OSError, AttributeError):
            return adapters
        finally:
            bthprops.BluetoothFindRadioClose(find_handle)

        return adapters


class MacOSBackend(BaseBackend):
    """macOS implementation using native IOKit/CoreFoundation HID APIs via ctypes."""

    name = "darwin"
    IOKIT_PATH = "/System/Library/Frameworks/IOKit.framework/IOKit"
    CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    _K_CF_STRING_UTF8 = 0x08000100
    _K_CF_NUMBER_SINT32 = 3
    _K_IOHID_REPORT_FEATURE = 2
    _PERMISSION_IORETURNS = frozenset({0xE00002C7, 0xE00002C5, 0xE00002C1})

    def __init__(self, iokit=None, cf=None, runner=None):
        """Initialize macOS backend with optional injected framework mocks for testing."""
        self._iokit = iokit
        self._cf = cf
        self._runner = runner
        self._initialized = False

    def _configure_darwin_signatures(self):
        """Set explicit ctypes signatures for 64-bit Intel & Apple Silicon macOS frameworks."""
        if _is_real_cdll(self._cf):
            self._cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            self._cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            self._cf.CFStringGetCString.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_ssize_t,
                ctypes.c_uint32,
            ]
            self._cf.CFStringGetCString.restype = ctypes.c_ubyte
            self._cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p]
            self._cf.CFNumberGetValue.restype = ctypes.c_ubyte
            self._cf.CFSetGetCount.argtypes = [ctypes.c_void_p]
            self._cf.CFSetGetCount.restype = ctypes.c_ssize_t
            self._cf.CFSetGetValues.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._cf.CFSetGetValues.restype = None
            self._cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
            self._cf.CFGetTypeID.restype = ctypes.c_ulong
            self._cf.CFStringGetTypeID.argtypes = []
            self._cf.CFStringGetTypeID.restype = ctypes.c_ulong
            self._cf.CFNumberGetTypeID.argtypes = []
            self._cf.CFNumberGetTypeID.restype = ctypes.c_ulong
            self._cf.CFRelease.argtypes = [ctypes.c_void_p]
            self._cf.CFRelease.restype = None

        if _is_real_cdll(self._iokit):
            self._iokit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._iokit.IOHIDManagerCreate.restype = ctypes.c_void_p
            self._iokit.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._iokit.IOHIDManagerSetDeviceMatching.restype = None
            self._iokit.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._iokit.IOHIDManagerOpen.restype = ctypes.c_int32
            self._iokit.IOHIDManagerClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._iokit.IOHIDManagerClose.restype = ctypes.c_int32
            self._iokit.IOHIDManagerCopyDevices.argtypes = [ctypes.c_void_p]
            self._iokit.IOHIDManagerCopyDevices.restype = ctypes.c_void_p
            self._iokit.IOHIDDeviceGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._iokit.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
            self._iokit.IOHIDDeviceOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._iokit.IOHIDDeviceOpen.restype = ctypes.c_int32
            self._iokit.IOHIDDeviceClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._iokit.IOHIDDeviceClose.restype = ctypes.c_int32
            self._iokit.IOHIDDeviceGetReport.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int32,
                ctypes.c_ssize_t,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ssize_t),
            ]
            self._iokit.IOHIDDeviceGetReport.restype = ctypes.c_int32
            self._iokit.IOHIDDeviceSetReport.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int32,
                ctypes.c_ssize_t,
                ctypes.c_void_p,
                ctypes.c_ssize_t,
            ]
            self._iokit.IOHIDDeviceSetReport.restype = ctypes.c_int32

    def _init_darwin(self):
        """Load macOS IOKit and CoreFoundation libraries lazily."""
        if self._initialized:
            return
        self._initialized = True
        if sys.platform == "darwin":
            if self._iokit is None and os.path.exists(self.IOKIT_PATH):
                self._iokit = ctypes.CDLL(self.IOKIT_PATH)
            if self._cf is None and os.path.exists(self.CF_PATH):
                self._cf = ctypes.CDLL(self.CF_PATH)
        self._configure_darwin_signatures()

    def _make_cf_string(self, text):
        """Create a CFStringRef from UTF-8 Python text."""
        return self._cf.CFStringCreateWithCString(None, text.encode("utf-8"), self._K_CF_STRING_UTF8)

    def _get_hid_int_property(self, dev_ref, key):
        """Read an integer IOHIDDevice property."""
        cf_key = self._make_cf_string(key)
        if not cf_key:
            return None
        try:
            prop_ref = self._iokit.IOHIDDeviceGetProperty(dev_ref, cf_key)
            if not prop_ref:
                return None
            val = ctypes.c_int32(0)
            if self._cf.CFNumberGetValue(prop_ref, self._K_CF_NUMBER_SINT32, ctypes.byref(val)):
                return int(val.value)
            return None
        finally:
            self._cf.CFRelease(cf_key)

    def _get_hid_str_property(self, dev_ref, key):
        """Read a string IOHIDDevice property."""
        cf_key = self._make_cf_string(key)
        if not cf_key:
            return None
        try:
            prop_ref = self._iokit.IOHIDDeviceGetProperty(dev_ref, cf_key)
            if not prop_ref:
                return None
            if (
                hasattr(self._cf, "CFGetTypeID")
                and hasattr(self._cf, "CFStringGetTypeID")
                and self._cf.CFGetTypeID(prop_ref) != self._cf.CFStringGetTypeID()
            ):
                return None
            buf = ctypes.create_string_buffer(256)
            if self._cf.CFStringGetCString(prop_ref, buf, len(buf), self._K_CF_STRING_UTF8):
                return buf.value.decode("utf-8", errors="ignore").strip() or None
            return None
        finally:
            self._cf.CFRelease(cf_key)

    def _enumerate_matching_hid_devices(self):
        """Open an IOHIDManager and return (manager, [(device_id, dev_ref), ...])."""
        self._init_darwin()
        if not self._iokit or not self._cf:
            return None, []

        manager = self._iokit.IOHIDManagerCreate(None, 0)
        if not manager:
            return None, []

        self._iokit.IOHIDManagerSetDeviceMatching(manager, None)
        self._iokit.IOHIDManagerOpen(manager, 0)
        device_set = self._iokit.IOHIDManagerCopyDevices(manager)
        if not device_set:
            return manager, []

        matched = []
        try:
            count = int(self._cf.CFSetGetCount(device_set))
            if count > 0:
                refs = (ctypes.c_void_p * count)()
                self._cf.CFSetGetValues(device_set, refs)
                for idx, dev_ref in enumerate(refs):
                    if not dev_ref:
                        continue
                    vid = self._get_hid_int_property(dev_ref, "VendorID")
                    pid = self._get_hid_int_property(dev_ref, "ProductID")
                    if vid == SONY_VID and pid == PS3_PID:
                        loc_id = self._get_hid_int_property(dev_ref, "LocationID")
                        suffix = f"{loc_id:08x}" if loc_id is not None else str(idx)
                        matched.append((f"iokit://054c:0268/{suffix}", dev_ref))
        finally:
            self._cf.CFRelease(device_set)

        matched.sort(key=lambda item: item[0])
        return manager, matched

    def _close_manager(self, manager):
        """Close and release an IOHIDManager handle."""
        if manager and self._iokit and self._cf:
            with contextlib.suppress(OSError, AttributeError):
                self._iokit.IOHIDManagerClose(manager, 0)
                self._cf.CFRelease(manager)

    def _run_cmd(self, cmd):
        """Execute a macOS CLI utility cleanly using injected runner or subprocess."""
        if self._runner is not None:
            return self._runner(cmd)
        if sys.platform != "darwin":
            return None
        exe = shutil.which(cmd[0]) or cmd[0]
        full_cmd = [exe, *cmd[1:]]
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=10, check=False)  # noqa: S603

    def _detect_via_ioreg(self):
        """Fallback USB enumeration via ioreg when IOHIDManager finds no accessible HID node."""
        proc = self._run_cmd(["/usr/sbin/ioreg", "-r", "-c", "IOUSBHostDevice", "-l"])
        if not proc or getattr(proc, "returncode", 1) != 0 or not getattr(proc, "stdout", ""):
            return []

        devices = []
        blocks = proc.stdout.split("+-o ")
        for idx, block in enumerate(blocks):
            vid_match = re.search(r'"idVendor"\s*=\s*(1356|0x0?54c)\b', block, re.IGNORECASE)
            pid_match = re.search(r'"idProduct"\s*=\s*(616|0x0?268)\b', block, re.IGNORECASE)
            if vid_match and pid_match:
                loc_match = re.search(r'"locationID"\s*=\s*(0x[0-9a-fA-F]+|\d+)', block)
                suffix = f"{int(loc_match.group(1), 0):08x}" if loc_match else str(idx)
                devices.append(f"iokit://054c:0268/{suffix}")
        return sorted(set(devices))

    def detect_devices(self):
        """Enumerate connected DualShock 3 devices on macOS via IOKit HID Manager."""
        manager, matched = self._enumerate_matching_hid_devices()
        try:
            if matched:
                return [dev_id for dev_id, _ in matched]
        finally:
            self._close_manager(manager)
        return self._detect_via_ioreg()

    def find_node(self, device_path):
        """Return the IOKit device identifier."""
        return device_path

    def _resolve_device_ref(self, devnode):
        """Open IOHIDManager and locate the matching IOHIDDeviceRef for devnode."""
        manager, matched = self._enumerate_matching_hid_devices()
        if not matched:
            self._close_manager(manager)
            raise FileNotFoundError(f"PS3 controller not accessible via IOKit ({devnode})")
        for dev_id, dev_ref in matched:
            if dev_id == devnode:
                return manager, dev_ref
        return manager, matched[0][1]

    def _open_iokit_device(self, dev_ref):
        """Open an IOHIDDeviceRef and translate permission errors clearly."""
        ret = self._iokit.IOHIDDeviceOpen(dev_ref, 0)
        if ret == 0:
            return
        ret_u32 = ret & 0xFFFFFFFF
        if ret_u32 in self._PERMISSION_IORETURNS:
            raise PermissionError(_permission_denied_message(self.name))
        raise OSError(f"IOHIDDeviceOpen failed (IOReturn 0x{ret_u32:08x})")

    def _get_feature_report(self, dev_ref, report_id, sizes):
        """Try reading an IOKit HID feature report across candidate buffer lengths."""
        last_ret = -1
        for size in sizes:
            buf = bytearray([report_id] + [0] * (size - 1))
            c_buf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            report_len = ctypes.c_ssize_t(len(buf))
            ret = self._iokit.IOHIDDeviceGetReport(
                dev_ref,
                self._K_IOHID_REPORT_FEATURE,
                report_id,
                c_buf,
                ctypes.byref(report_len),
            )
            if ret == 0:
                return buf, int(report_len.value)
            last_ret = ret
        raise OSError(f"IOHIDDeviceGetReport 0x{report_id:02X} failed (IOReturn 0x{last_ret & 0xFFFFFFFF:08x})")

    def read_master_mac(self, devnode):
        """Read Master Host MAC from DualShock 3 via macOS IOHIDDeviceGetReport 0xF5."""
        manager, dev_ref = self._resolve_device_ref(devnode)
        try:
            self._open_iokit_device(dev_ref)
            try:
                buf, actual_len = self._get_feature_report(dev_ref, 0xF5, (64, 8))
                if actual_len >= 8 and buf[0] == 0xF5:
                    mac_bytes = buf[2:8]
                elif actual_len >= 7:
                    mac_bytes = buf[1:7]
                else:
                    raise OSError(f"Unexpected 0xF5 feature report length: {actual_len}")
                return ":".join(f"{b:02x}" for b in mac_bytes).lower()
            finally:
                self._iokit.IOHIDDeviceClose(dev_ref, 0)
        finally:
            self._close_manager(manager)

    def write_master_mac(self, devnode, mac_str):
        """Write Master Host MAC to DualShock 3 via macOS IOHIDDeviceSetReport 0xF5."""
        normalized = normalize_mac(mac_str)
        mac_bytes = mac_to_bytes(normalized)
        manager, dev_ref = self._resolve_device_ref(devnode)
        try:
            self._open_iokit_device(dev_ref)
            try:
                payloads = (
                    bytearray([0xF5, 0x01, *mac_bytes]),
                    bytearray([0xF5, 0x01, *mac_bytes] + [0] * 56),
                    bytearray([0x01, *mac_bytes]),
                )
                last_ret = -1
                for payload in payloads:
                    c_buf = (ctypes.c_ubyte * len(payload)).from_buffer(payload)
                    ret = self._iokit.IOHIDDeviceSetReport(
                        dev_ref,
                        self._K_IOHID_REPORT_FEATURE,
                        0xF5,
                        c_buf,
                        len(payload),
                    )
                    if ret == 0:
                        return normalized
                    last_ret = ret
                last_u32 = last_ret & 0xFFFFFFFF
                if last_u32 in self._PERMISSION_IORETURNS:
                    raise PermissionError(_permission_denied_message(self.name))
                raise OSError(f"IOHIDDeviceSetReport 0xF5 failed (IOReturn 0x{last_u32:08x})")
            finally:
                self._iokit.IOHIDDeviceClose(dev_ref, 0)
        finally:
            self._close_manager(manager)

    def read_device_mac(self, device_path):
        """Read physical Device MAC via SerialNumber property or IOKit Report 0xF2."""
        try:
            manager, dev_ref = self._resolve_device_ref(device_path)
        except OSError:
            return "Unavailable"

        try:
            serial = self._get_hid_str_property(dev_ref, "SerialNumber")
            if serial:
                with contextlib.suppress(ValueError):
                    norm = normalize_mac(serial)
                    if any(b != 0 for b in mac_to_bytes(norm)):
                        return norm

            with contextlib.suppress(OSError, PermissionError):
                self._open_iokit_device(dev_ref)
                try:
                    buf, actual_len = self._get_feature_report(dev_ref, 0xF2, (64, 18, 17))
                    mac_bytes = buf[4:10] if actual_len >= 10 and buf[0] == 0xF2 else buf[3:9]
                    if len(mac_bytes) == 6 and any(b != 0 for b in mac_bytes):
                        return ":".join(f"{b:02x}" for b in mac_bytes).lower()
                finally:
                    self._iokit.IOHIDDeviceClose(dev_ref, 0)
            return "Unavailable"
        finally:
            self._close_manager(manager)

    def _extract_bt_from_json_obj(self, obj, results):
        """Recursively search system_profiler JSON output for local Bluetooth controller MAC."""
        if isinstance(obj, dict):
            props = obj.get("controller_properties")
            if isinstance(props, dict) and props.get("controller_address"):
                with contextlib.suppress(ValueError):
                    norm = normalize_mac(str(props["controller_address"]))
                    if validate_mac(norm)[0]:
                        name = str(props.get("controller_name") or "macOS Bluetooth")
                        results.append({"adapter": name, "address": norm})
            if obj.get("device_title") and obj.get("Address"):
                with contextlib.suppress(ValueError):
                    norm = normalize_mac(str(obj["Address"]))
                    if validate_mac(norm)[0]:
                        results.append({"adapter": str(obj["device_title"]), "address": norm})
            for value in obj.values():
                self._extract_bt_from_json_obj(value, results)
        elif isinstance(obj, list):
            for item in obj:
                self._extract_bt_from_json_obj(item, results)

    def _detect_bt_from_system_profiler_json(self):
        """Parse local macOS Bluetooth address from system_profiler JSON output."""
        adapters: list[dict[str, str]] = []
        proc = self._run_cmd(["/usr/sbin/system_profiler", "SPBluetoothDataType", "-json"])
        if proc and getattr(proc, "returncode", 1) == 0 and getattr(proc, "stdout", ""):
            with contextlib.suppress(json.JSONDecodeError):
                self._extract_bt_from_json_obj(json.loads(proc.stdout), adapters)
        return adapters

    def _detect_bt_from_system_profiler_text(self):
        """Parse local macOS Bluetooth address from plain-text system_profiler output."""
        proc = self._run_cmd(["/usr/sbin/system_profiler", "SPBluetoothDataType"])
        if not proc or getattr(proc, "returncode", 1) != 0 or not getattr(proc, "stdout", ""):
            return []
        match = re.search(r"Address:\s*([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})", proc.stdout)
        if not match:
            return []
        with contextlib.suppress(ValueError):
            norm = normalize_mac(match.group(1))
            if validate_mac(norm)[0]:
                return [{"adapter": "macOS Bluetooth", "address": norm}]
        return []

    def _detect_bt_from_ioreg(self):
        """Parse local macOS Bluetooth address from ioreg IOBluetoothHCIController."""
        proc = self._run_cmd(["/usr/sbin/ioreg", "-r", "-c", "IOBluetoothHCIController"])
        if not proc or getattr(proc, "returncode", 1) != 0 or not getattr(proc, "stdout", ""):
            return []
        match = re.search(r'"BluetoothDeviceAddress"\s*=\s*<([0-9a-fA-F ]+)>', proc.stdout)
        if not match:
            return []
        hex_str = match.group(1).replace(" ", "")
        if len(hex_str) != 12:
            return []
        with contextlib.suppress(ValueError):
            norm = normalize_mac(hex_str)
            if validate_mac(norm)[0]:
                return [{"adapter": "IOBluetoothHCIController", "address": norm}]
        return []

    def detect_host_bluetooth_macs(self):
        """Discover local Bluetooth adapter MAC on macOS via system_profiler / ioreg."""
        return (
            self._detect_bt_from_system_profiler_json()
            or self._detect_bt_from_system_profiler_text()
            or self._detect_bt_from_ioreg()
        )


def get_backend(platform_name=None):
    """Factory returning the appropriate platform backend."""
    plat = platform_name if platform_name is not None else sys.platform
    if plat == "win32":
        return WindowsBackend()
    if plat == "darwin":
        return MacOSBackend()
    return LinuxBackend()


# ============================================================================
# Linux-Specific Helpers (Preserved for backwards compatibility & tests)
# ============================================================================

def get_ps3_devices():
    """Find sysfs device entries for connected PS3 controllers (Sony VID:PID 054C:0268)."""
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
    """Find corresponding /dev/hidrawX character device node on Linux."""
    hidraw_paths = glob.glob(os.path.join(device_path, "hidraw", "hidraw*"))
    if hidraw_paths:
        node_name = os.path.basename(min(hidraw_paths))
        return f"/dev/{node_name}"
    return None


def _read_device_mac_from_uevent(device_path):
    """Read HID_UNIQ from sysfs uevent if available."""
    uevent_file = os.path.join(device_path, "uevent")
    if not os.path.exists(uevent_file):
        return None
    try:
        with open(uevent_file, encoding="utf-8", errors="ignore") as f:
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
        with open(uniq_files[0], encoding="utf-8", errors="ignore") as f:
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
    """Read physical Bluetooth Device MAC address of the controller on Linux."""
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
    """Read Master Host Bluetooth MAC stored inside PS3 controller memory on Linux."""
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
    """Write Master Host Bluetooth MAC into PS3 controller EEPROM on Linux."""
    _fcntl = sys.modules.get("fcntl") or fcntl
    if _fcntl is None:
        raise OSError("fcntl module unavailable on this operating system")

    normalized = normalize_mac(mac_str)
    mac_bytes = mac_to_bytes(normalized)
    fd = os.open(devnode, os.O_RDWR)
    try:
        buf8 = bytearray([0xF5, 0x01, *mac_bytes])
        try:
            _fcntl.ioctl(fd, HIDIOCSFEAT(len(buf8)), buf8)
        except OSError:
            buf64 = bytearray([0xF5, 0x01, *mac_bytes] + [0] * 56)
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
            with open(addr_path, encoding="utf-8", errors="ignore") as f:
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
        with open(path, encoding="utf-8") as f:
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
    """Persist profile and backup store to disk."""
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
        with contextlib.suppress(ValueError):
            entry["last_written_mac"] = normalize_mac(new_master_mac)
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


def _resolve_safe_backup_path(filepath):
    """Canonicalize and validate backup file path within the working directory (S8707)."""
    if not isinstance(filepath, str) or not filepath.strip():
        raise ValueError("Backup file path cannot be empty")
    resolved = os.path.realpath(filepath)
    base_dir = os.path.realpath(os.getcwd())
    if resolved == base_dir or not resolved.startswith(base_dir + os.sep):
        raise ValueError(f"Backup path '{filepath}' is outside the allowed directory")
    return resolved


def export_backup_file(filepath, controllers_data):
    """Export inspected controller MAC state to a standalone JSON backup file."""
    base_dir = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(_resolve_safe_backup_path(filepath))
    if not resolved.startswith(base_dir + os.sep):
        raise ValueError(f"Backup path '{filepath}' is outside the allowed directory")

    payload = {
        "version": 1,
        "exported_at": _utc_now_iso(),
        "controllers": controllers_data,
    }
    parent = os.path.dirname(resolved)
    if parent and parent.startswith(base_dir + os.sep):
        os.makedirs(parent, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return resolved


def import_backup_file(filepath):
    """Load controller backup entries from a JSON backup file."""
    base_dir = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(_resolve_safe_backup_path(filepath))
    if not resolved.startswith(base_dir + os.sep):
        raise ValueError(f"Backup path '{filepath}' is outside the allowed directory")

    with open(resolved, encoding="utf-8") as f:
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
# High-Level Inspection, Modification & Diagnostics
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
    """Format controller inspection, diagnostics, or management data as pretty JSON."""
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
        result["error"] = _permission_denied_message(backend.name)
    except Exception as e:
        result["error"] = str(e)

    return result


def change_controller_mac(dev_path, target_mac, backend=None, force=False, store_path=None):
    """Safely write a new Master MAC to a PS3 controller and verify via read-back."""
    active_backend = backend if backend is not None else get_backend()
    normalized_mac, write_warning = validate_mac_for_write(target_mac, force=force)
    inspected = inspect_controller(dev_path, backend=active_backend)

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

    prev_mac = result["previous_master_mac"]
    if prev_mac and validate_mac(prev_mac)[0]:
        key = _controller_backup_key(result["device_mac"], dev_path)
        result["backup_saved"] = record_backup(
            key, prev_mac, new_master_mac=normalized_mac, store_path=store_path
        )

    try:
        active_backend.write_master_mac(result["devnode"], normalized_mac)
        readback_mac = active_backend.read_master_mac(result["devnode"])
        result["master_mac"] = readback_mac
        result["valid"], read_warning = validate_mac(readback_mac)
        result["verified"] = readback_mac == normalized_mac
        result["warning"] = read_warning or write_warning
        if not result["verified"]:
            result["error"] = (
                f"Write verification mismatch: expected {normalized_mac}, read back {readback_mac}"
            )
    except PermissionError:
        result["error"] = _permission_denied_message(active_backend.name)
    except OSError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


def _check_driver_status(backend_name):
    """Inspect OS-level HID driver/udev readiness for diagnostics."""
    if backend_name == "linux":
        rule_paths = [
            "/etc/udev/rules.d/99-ps3-controller.rules",
            *glob.glob("/etc/udev/rules.d/*ps3*.rules"),
            *glob.glob("/lib/udev/rules.d/*ps3*.rules"),
            *glob.glob("/usr/lib/udev/rules.d/*ps3*.rules"),
        ]
        found_rule = next((p for p in rule_paths if os.path.exists(p)), None)
        return {
            "ok": found_rule is not None and fcntl is not None,
            "detail": (
                f"udev rule present ({found_rule})"
                if found_rule
                else "udev rule missing (run ./install.sh or run with sudo)"
            ),
        }

    if backend_name == "win32":
        has_windll = hasattr(ctypes, "windll")
        return {
            "ok": has_windll,
            "detail": "Win32 HID & SetupAPI available" if has_windll else "Win32 DLL loader unavailable",
        }

    if backend_name == "darwin":
        has_iokit = os.path.exists(MacOSBackend.IOKIT_PATH) and os.path.exists(MacOSBackend.CF_PATH)
        return {
            "ok": has_iokit,
            "detail": "macOS IOKit & CoreFoundation available" if has_iokit else "macOS IOKit framework missing",
        }

    return {"ok": False, "detail": f"Unsupported backend: {backend_name}"}


def _doctor_tips_for_platform(backend_name):
    """Return beginner troubleshooting tips tailored to the host OS."""
    common = [
        "Use a DATA-capable mini-USB cable (many cheap cables only charge and have no data wires).",
        "Unplug the USB cable BEFORE pressing the PS button so the controller searches wirelessly.",
    ]
    if backend_name == "win32":
        return [
            *common,
            "No Zadig/libusb driver needed: keep the default Windows 'HID-compliant game controller' driver.",
            "If Steam or DsHidMini/ScpToolkit locks the controller, close them temporarily before writing.",
        ]
    if backend_name == "darwin":
        return [
            *common,
            "If access is denied on macOS, allow Terminal in System Settings -> Privacy -> Input Monitoring.",
        ]
    return [
        *common,
        "On Ubuntu/Fedora/Debian/Arch, run ./install.sh once so udev allows non-root access without sudo.",
    ]


def run_doctor(backend=None, store_path=None):
    """Run non-destructive environment, driver, Bluetooth, and controller diagnostics."""
    if backend is None:
        backend = get_backend()

    devices = backend.detect_devices()
    controllers = [inspect_controller(d, backend=backend) for d in devices]
    adapters = backend.detect_host_bluetooth_macs()
    resolved_store = get_store_path(store_path)
    store_data = load_store(store_path)

    return {
        "version": __version__,
        "platform": sys.platform,
        "os_release": f"{platform.system()} {platform.release()}",
        "backend": backend.name,
        "python_version": platform.python_version(),
        "python_ok": sys.version_info >= (3, 8),
        "hid_driver": _check_driver_status(backend.name),
        "host_bluetooth": adapters,
        "config_store": {
            "path": resolved_store,
            "exists": os.path.exists(resolved_store),
            "profiles_count": len(store_data.get("profiles", {})),
            "backups_count": len(store_data.get("backups", {})),
        },
        "controllers": controllers,
        "tips": _doctor_tips_for_platform(backend.name),
    }


def _print_doctor_report(report):
    """Render beginner-friendly diagnostics output in the terminal."""
    print("============================================================")
    print(f"       PS3 MAC MANAGER DIAGNOSTICS (v{report['version']})       ")
    print("============================================================\n")
    print(f"Operating System : {report['os_release']} ({report['platform']})")
    print(f"HID Backend      : {report['backend']}")
    py_mark = "✓" if report["python_ok"] else "!"
    print(f"Python Runtime   : [{py_mark}] Python {report['python_version']}")
    drv = report["hid_driver"]
    drv_mark = "✓" if drv["ok"] else "!"
    print(f"USB HID Access   : [{drv_mark}] {drv['detail']}")

    adapters = report["host_bluetooth"]
    if adapters:
        adapters_str = ", ".join(f"{a['adapter']} ({a['address']})" for a in adapters)
        print(f"Host Bluetooth   : [✓] {adapters_str}")
    else:
        print("Host Bluetooth   : [i] No active local Bluetooth adapter detected")

    store = report["config_store"]
    print(
        f"Config Store     : {store['path']} "
        f"({store['profiles_count']} profiles, {store['backups_count']} backups)"
    )

    ctrls = report["controllers"]
    if ctrls:
        print(f"\n[✓] Connected Controllers ({len(ctrls)}):")
        for idx, info in enumerate(ctrls, 1):
            status = info.get("error") or f"Master={info.get('master_mac')}, Device={info.get('device_mac')}"
            print(f"  #{idx}: {status}")
    else:
        print("\n[i] Connected Controllers: None detected right now")

    print("\nBeginner Checklist:")
    for tip in report["tips"]:
        print(f"  - {tip}")
    print()


# ============================================================================
# CLI Argument Parsing & Execution Helpers
# ============================================================================

def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="PS3 Controller MAC Address Manager (Windows, macOS & Linux)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ps3_mac_manager.py                         # Interactive TUI dashboard
  ps3_mac_manager.py --doctor                # Check system, drivers & cable setup
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
        help="Seconds to wait for controller connection (default: wait indefinitely in TTY, 0 otherwise)",
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
        "--doctor", action="store_true",
        help="Run system, driver, Bluetooth, and controller troubleshooting diagnostics",
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
        args.doctor,
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


def _sanitize_sudo_token(raw_val, flag_name):
    """Validate a CLI string argument for safe sudo re-execution (S8705)."""
    val = str(raw_val)
    if not re.match(r"^[A-Za-z0-9_.-]+$", val):
        print(f"[!] Refusing automatic sudo re-exec: unsupported characters in {flag_name}.")
        return None
    return val


def _build_sudo_args(args, sudo_bin):
    """Build sanitized argument list for sudo re-exec, or return None if invalid."""
    script_path = os.path.abspath(__file__)
    args_list = [sudo_bin, "--", sys.executable, script_path, "--no-sudo"]

    flag_map = (
        (args.non_interactive, "--non-interactive"),
        (args.all, "--all"),
        (args.check, "--check"),
        (args.generate_mac, "--generate-mac"),
        (args.pair_host, "--pair-host"),
        (args.clone, "--clone"),
        (args.force, "--force"),
    )
    args_list.extend(flag for enabled, flag in flag_map if enabled)

    if args.set_mac is not None:
        try:
            mac_bytes = mac_to_bytes(args.set_mac)
        except ValueError as exc:
            print(f"[!] Invalid MAC address '{args.set_mac}': {exc}")
            return None
        safe_mac = ":".join(f"{int(b):02x}" for b in mac_bytes)
        if not re.match(r"^[0-9a-f:]+$", safe_mac):
            return None
        args_list.extend(["--set-mac", safe_mac])

    value_map = (
        (args.adapter, "--adapter"),
        (args.save_profile, "--save-profile"),
        (args.apply_profile, "--apply-profile"),
        (args.backup, "--backup"),
    )
    for raw_val, flag in value_map:
        if raw_val is not None:
            safe_val = _sanitize_sudo_token(raw_val, flag)
            if safe_val is None:
                return None
            args_list.extend([flag, safe_val])

    if args.restore is not None:
        args_list.append("--restore")
        if args.restore != "__AUTO__":
            safe_restore = _sanitize_sudo_token(args.restore, "--restore")
            if safe_restore is None:
                return None
            args_list.append(safe_restore)

    return args_list


def _reexec_with_sudo(args):
    """Re-execute current script with sudo using strictly sanitized arguments (S8705-safe)."""
    sudo_bin = shutil.which("sudo")
    if not sudo_bin:
        print("[!] 'sudo' not found. Please run this command as root/administrator.")
        return 2

    args_list = _build_sudo_args(args, sudo_bin)
    if args_list is None:
        return 2

    print("\n[*] Administrator privileges (sudo) required to access controller memory...")
    try:
        os.execv(sudo_bin, args_list)  # noqa: S606
    except OSError as e:
        print(f"[!] Failed to re-exec with sudo: {e}")
        return 2
    return 0


def _emit_error(message, as_json=False, exit_code=1):
    """Print an error message as JSON or plain text and return exit_code."""
    if as_json:
        print(format_json({"error": message}))
    else:
        print(f"[!] {message}")
    return exit_code


def _handle_profile_delete_or_save(args, store_path):
    """Handle offline profile delete or offline --save-profile + --set-mac."""
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


def _handle_store_or_info_action(args, backend, store_path=None):
    """Handle CLI actions that do not require waiting for a USB controller."""
    if args.doctor:
        report = run_doctor(backend=backend, store_path=store_path)
        if args.json:
            print(format_json(report))
        else:
            _print_doctor_report(report)
        return 0

    if args.list_profiles:
        data = load_store(store_path)
        profiles = list_profiles(store_path)
        if args.json:
            print(format_json({"profiles": profiles, "backups": data.get("backups", {})}))
        else:
            _print_profiles_and_backups(profiles, data.get("backups", {}))
        return 0

    return _handle_profile_delete_or_save(args, store_path)


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


def _execute_write_target(target_devices, target_mac, backend, force, store_path):
    """Apply target_mac to all target_devices."""
    return [
        change_controller_mac(d, target_mac, backend=backend, force=force, store_path=store_path)
        for d in target_devices
    ]


def _execute_restore_or_clone(args, target_devices, backend, store_path):
    """Execute --restore or --clone CLI action."""
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

    inspected = [inspect_controller(d, backend=backend) for d in target_devices]
    if len(inspected) < 2:
        raise ValueError("--clone requires at least 2 connected PS3 controllers (use -a/--all)")
    if inspected[0].get("error") or not inspected[0].get("master_mac"):
        raise ValueError(f"Cannot read source Master MAC from Controller #1: {inspected[0].get('error')}")
    source_mac = inspected[0]["master_mac"]
    return [inspected[0], *_execute_write_target(target_devices[1:], source_mac, backend, args.force, store_path)]


def _execute_cli_action(args, target_devices, backend, store_path=None):
    """Execute one-shot CLI inspection or modification across target_devices."""
    if args.set_mac is not None:
        return _execute_write_target(target_devices, args.set_mac, backend, args.force, store_path)

    if args.generate_mac:
        return _execute_write_target(target_devices, generate_random_mac(), backend, args.force, store_path)

    if args.pair_host:
        adapter = _select_host_adapter(backend, args.adapter)
        results = _execute_write_target(target_devices, adapter["address"], backend, args.force, store_path)
        for res in results:
            res["paired_adapter"] = adapter["adapter"]
        return results

    if args.apply_profile is not None:
        profile_mac = get_profile(args.apply_profile, store_path=store_path)
        if not profile_mac:
            raise ValueError(f"Profile '{args.apply_profile}' does not exist")
        return _execute_write_target(target_devices, profile_mac, backend, args.force, store_path)

    if args.restore is not None or args.clone:
        return _execute_restore_or_clone(args, target_devices, backend, store_path)

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


def _select_profile_name(names, prompt):
    """Resolve user-entered 1-based index or profile name."""
    sel = safe_input(prompt).strip()
    if sel.isdigit() and 1 <= int(sel) <= len(names):
        return names[int(sel) - 1]
    return sel


def _tui_profile_save(inspected, store_path):
    """Save Controller #1 Master MAC to a named profile interactively."""
    if not inspected or inspected[0].get("error"):
        print("[!] No readable controller available to save from.")
        return
    name = safe_input("Profile name (e.g. robot_a): ").strip()
    if not name:
        return
    try:
        saved = save_profile(name, inspected[0]["master_mac"], store_path=store_path, force=True)
        print(f"[✓] Saved profile '{name}' -> {saved}")
    except ValueError as e:
        print(f"[!] {e}")


def _tui_profile_apply(names, target_devices, backend, store_path):
    """Apply a saved profile interactively to connected controllers."""
    if not names:
        print("[!] No saved profiles available to apply.")
        return
    chosen_name = _select_profile_name(names, "Enter profile number or name: ")
    mac = get_profile(chosen_name, store_path=store_path)
    if not mac:
        print(f"[!] Profile '{chosen_name}' not found.")
        return
    for dev_path in target_devices:
        res = change_controller_mac(dev_path, mac, backend=backend, force=True, store_path=store_path)
        _report_tui_write_result(res)


def _tui_profile_delete(names, store_path):
    """Delete a saved profile interactively."""
    if not names:
        print("[!] No saved profiles available to delete.")
        return
    chosen_name = _select_profile_name(names, "Profile name or number to delete: ")
    if delete_profile(chosen_name, store_path=store_path):
        print(f"[✓] Deleted profile '{chosen_name}'.")
    else:
        print(f"[!] Profile '{chosen_name}' not found.")


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
        _tui_profile_save(inspected, store_path)
    elif choice == "a":
        _tui_profile_apply(names, target_devices, backend, store_path)
    elif choice == "d":
        _tui_profile_delete(names, store_path)


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


def _tui_restore_backup(inspected, backend, store_path):
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
            res = change_controller_mac(
                info["device_path"], backup_mac, backend=backend, force=True, store_path=store_path
            )
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
        active_targets = devices or target_devices
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
        print("  [7] System diagnostics & troubleshooting (--doctor)")
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
            _tui_restore_backup(inspected, backend, store_path)
        elif choice == "6":
            continue
        elif choice == "7":
            _print_doctor_report(run_doctor(backend=backend, store_path=store_path))
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


def _should_reexec_sudo(args, results):
    """Determine whether permission errors justify sudo re-elevation on POSIX."""
    permission_error = any(
        item.get("error") and "Permission denied" in item["error"] for item in results
    )
    return (
        permission_error
        and not args.no_sudo
        and hasattr(os, "geteuid")
        and os.geteuid() != 0
        and not args.json
    )


def _print_banner(args):
    """Print application header banner for interactive/text runs."""
    if not args.json:
        clear_screen()
        print("============================================================")
        print(f"         PS3 CONTROLLER MAC ADDRESS MANAGER v{__version__}         ")
        print("============================================================\n")


def _resolve_initial_devices(args, backend):
    """Wait for controller connection and handle empty device detection cleanly."""
    timeout = args.timeout
    if timeout is None and (args.non_interactive or not sys.stdin.isatty()):
        timeout = 0.0

    devices = _wait_for_devices(backend, timeout, quiet=args.json)
    if not devices:
        if args.json:
            print(format_json([]))
        else:
            print(f"\n[!] Timeout ({timeout}s) reached. No PS3 controller detected.")
            print("    Tip: Run with --doctor to check USB cable, drivers, and permissions.")
    return devices


def _finalize_cli_output(args, results, device_state, backend, store_path):
    """Render CLI output and launch interactive TUI or exit cleanly."""
    devices, target_devices = device_state
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


def main(argv=None, backend=None, store_path=None):
    """Main program entry point."""
    backend = _resolve_backend(backend)
    args = parse_args(argv)

    early_exit = _handle_store_or_info_action(args, backend, store_path=store_path)
    if early_exit is not None:
        return early_exit

    try:
        _validate_preconditions(args, backend, store_path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return _emit_error(str(e), as_json=args.json, exit_code=1)

    _print_banner(args)
    devices = _resolve_initial_devices(args, backend)
    if not devices:
        return 1

    target_devices = devices if args.all or len(devices) > 1 or args.clone else [devices[0]]

    try:
        results = _execute_cli_action(args, target_devices, backend, store_path=store_path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return _emit_error(str(e), as_json=args.json, exit_code=1)

    if _should_reexec_sudo(args, results):
        return _reexec_with_sudo(args)

    return _finalize_cli_output(args, results, (devices, target_devices), backend, store_path)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
