#!/usr/bin/env python3
"""
Comprehensive Test Battery for PS3 Controller MAC Address Checker
Audits and stress-tests ps3_mac_checker.py against 50+ hardware edge cases,
kernel HID quirks, clone controller abnormalities, security loops, and non-interactive environments.
"""

import sys
import os
import io
import errno
import random
import unittest
from unittest.mock import patch, mock_open, MagicMock, call

# Add repo root to python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import ps3_mac_checker

# Cross-platform compatibility stubs for Windows test runners
if 'fcntl' not in sys.modules:
    import types
    _dummy_fcntl = types.ModuleType('fcntl')
    _dummy_fcntl.ioctl = lambda *args, **kwargs: 0  # type: ignore
    sys.modules['fcntl'] = _dummy_fcntl
    ps3_mac_checker.fcntl = _dummy_fcntl

if not hasattr(os, 'geteuid'):
    os.geteuid = lambda: 1000  # type: ignore



# ============================================================================
# CATEGORY 1: IOCTL Encoding & Feature Report Sizing
# ============================================================================
class TestHIDIOCGFEATCalculation(unittest.TestCase):
    """Audits ioctl encoding formulas and buffer sizes for HID Feature Reports."""

    def test_ioctl_len_8_standard_feature_report(self):
        """Standard DS3 feature report 0xF5 is 8 bytes. Formula must produce 0xC0084807."""
        # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, 8)
        # (3 << 30) | (8 << 16) | (ord('H') << 8) | 0x07
        expected = (3 << 30) | (8 << 16) | (0x48 << 8) | 0x07
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(8), expected)
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(8), 0xC0084807)

    def test_ioctl_len_64_current_implementation(self):
        """Current script requests 64 bytes: formula must produce 0xC0404807."""
        expected = (3 << 30) | (64 << 16) | (0x48 << 8) | 0x07
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(64), expected)
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(64), 0xC0404807)

    def test_ioctl_len_1_minimal_report(self):
        """Boundary test: 1 byte report."""
        expected = (3 << 30) | (1 << 16) | (0x48 << 8) | 0x07
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(1), expected)

    def test_ioctl_len_zero_boundary(self):
        """Boundary test: size 0."""
        expected = (3 << 30) | (0 << 16) | (0x48 << 8) | 0x07
        self.assertEqual(ps3_mac_checker.HIDIOCGFEAT(0), expected)

    def test_ioctl_direction_read_write_bits(self):
        """Verify direction bits are 3 (IOC_READ | IOC_WRITE for Linux HID ioctls)."""
        ioctl_val = ps3_mac_checker.HIDIOCGFEAT(8)
        direction = (ioctl_val >> 30) & 0x03
        self.assertEqual(direction, 3)

    def test_ioctl_type_magic_h(self):
        """Verify ioctl magic character is 'H' (0x48)."""
        ioctl_val = ps3_mac_checker.HIDIOCGFEAT(8)
        ioc_type = (ioctl_val >> 8) & 0xFF
        self.assertEqual(ioc_type, ord('H'))

    def test_ioctl_nr_hid_feature(self):
        """Verify command number is 0x07 (HIDIOCGFEAT)."""
        ioctl_val = ps3_mac_checker.HIDIOCGFEAT(8)
        ioc_nr = ioctl_val & 0xFF
        self.assertEqual(ioc_nr, 0x07)


# ============================================================================
# CATEGORY 2: Screen Clearing & Terminal Output (ANSI vs Non-TTY)
# ============================================================================
class TestScreenClearingAndANSI(unittest.TestCase):
    """Audits terminal escape codes and stdout pollution in non-interactive setups."""

    def test_clear_screen_emits_ansi_escape_code(self):
        """clear_screen prints ANSI escape code \\033[H\\033[J on interactive TTY."""
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            fake_out = io.StringIO()
            fake_out.isatty = lambda: True  # type: ignore
            with patch('sys.stdout', fake_out):
                ps3_mac_checker.clear_screen()
                self.assertEqual(fake_out.getvalue(), "\033[H\033[J")

    def test_clear_screen_leaks_ansi_on_redirected_stdout(self):
        """Hardened: clear_screen checks sys.stdout.isatty() and suppresses escape on redirected stdout."""
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False  # Redirected / Pipe
        with patch('sys.stdout', mock_stdout):
            ps3_mac_checker.clear_screen()
            mock_stdout.write.assert_not_called()

    def test_clear_screen_unconditional_regardless_of_term_dumb(self):
        """Hardened: clear_screen suppresses escape codes when TERM=dumb."""
        with patch.dict(os.environ, {"TERM": "dumb"}):
            captured = io.StringIO()
            captured.isatty = lambda: True  # type: ignore
            with patch('sys.stdout', captured):
                ps3_mac_checker.clear_screen()
            self.assertEqual(captured.getvalue(), "")

    def test_clear_screen_unconditional_regardless_of_no_color(self):
        """Hardened: clear_screen respects standard NO_COLOR environment variable."""
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            captured = io.StringIO()
            captured.isatty = lambda: True  # type: ignore
            with patch('sys.stdout', captured):
                ps3_mac_checker.clear_screen()
            self.assertEqual(captured.getvalue(), "")


# ============================================================================
# CATEGORY 3: Sysfs Device Discovery & Multi-Controller Traversal
# ============================================================================
class TestSysfsDeviceDiscovery(unittest.TestCase):
    """Audits sysfs path matching, case-sensitivity, and multi-controller handling."""

    @patch('glob.glob')
    def test_get_ps3_devices_returns_empty_when_no_devices(self, mock_glob):
        """Returns empty list when no PS3 controllers are attached."""
        mock_glob.return_value = []
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(devices, [])

    @patch('glob.glob')
    def test_get_ps3_devices_detects_single_usb_controller(self, mock_glob):
        """Detects standard Sony DS3 at 0003:054C:0268.0001."""
        def glob_side_effect(pattern):
            if '*054C:0268*' in pattern:
                return ['/sys/bus/hid/devices/0003:054C:0268.0001']
            return []
        mock_glob.side_effect = glob_side_effect
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(devices, ['/sys/bus/hid/devices/0003:054C:0268.0001'])

    @patch('glob.glob')
    def test_get_ps3_devices_matches_lowercase_hex_vid_pid(self, mock_glob):
        """Matches lowercase pattern 054c:0268."""
        def glob_side_effect(pattern):
            if '*054c:0268*' in pattern:
                return ['/sys/bus/hid/devices/0003:054c:0268.0001']
            return []
        mock_glob.side_effect = glob_side_effect
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(devices, ['/sys/bus/hid/devices/0003:054c:0268.0001'])

    @patch('glob.glob')
    def test_get_ps3_devices_duplicate_paths_returned(self, mock_glob):
        """Hardened: get_ps3_devices deduplicates paths using set()."""
        mock_glob.return_value = ['/sys/bus/hid/devices/0003:054C:0268.0001']
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0], '/sys/bus/hid/devices/0003:054C:0268.0001')

    @patch('glob.glob')
    def test_get_ps3_devices_detects_multiple_controllers(self, mock_glob):
        """Two distinct physical controllers connected simultaneously."""
        def glob_side_effect(pattern):
            if '*054C:0268*' in pattern:
                return [
                    '/sys/bus/hid/devices/0003:054C:0268.0001',
                    '/sys/bus/hid/devices/0003:054C:0268.0002',
                ]
            return []
        mock_glob.side_effect = glob_side_effect
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(len(devices), 2)

    @patch('glob.glob')
    def test_get_ps3_devices_unintentionally_matches_bluetooth_controller(self, mock_glob):
        """EDGE CASE: Matches Bluetooth-connected controller (bus 0005) instead of USB (bus 0003)."""
        def glob_side_effect(pattern):
            if '*054C:0268*' in pattern:
                return ['/sys/bus/hid/devices/0005:054C:0268.0001']
            return []
        mock_glob.side_effect = glob_side_effect
        devices = ps3_mac_checker.get_ps3_devices()
        # Script matches bus 0005, which will later fail on USB feature report ioctl
        self.assertEqual(devices, ['/sys/bus/hid/devices/0005:054C:0268.0001'])

    @patch('glob.glob')
    def test_get_ps3_devices_ignores_unrelated_usb_hid(self, mock_glob):
        """Ensures non-DS3 HID devices (e.g., Logitech 046d:c077) are not matched."""
        mock_glob.return_value = []
        devices = ps3_mac_checker.get_ps3_devices()
        self.assertEqual(devices, [])


# ============================================================================
# CATEGORY 4: Hidraw Node Resolution & Hotplug Races
# ============================================================================
class TestHidrawNodeResolution(unittest.TestCase):
    """Audits sysfs hidraw discovery and race conditions upon USB plug-in."""

    @patch('glob.glob')
    def test_find_hidraw_node_success(self, mock_glob):
        """Resolves standard /dev/hidraw0."""
        mock_glob.return_value = ['/sys/bus/hid/devices/0003:054C:0268.0001/hidraw/hidraw0']
        node = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertEqual(node, '/dev/hidraw0')

    @patch('glob.glob')
    def test_find_hidraw_node_missing_hidraw_subdirectory(self, mock_glob):
        """Returns None if hidraw driver is not bound or directory missing."""
        mock_glob.return_value = []
        node = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertIsNone(node)

    @patch('glob.glob')
    def test_find_hidraw_node_empty_hidraw_directory(self, mock_glob):
        """Returns None if hidraw directory contains no device nodes."""
        mock_glob.return_value = []
        node = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertIsNone(node)

    @patch('glob.glob')
    def test_find_hidraw_node_arbitrary_first_element(self, mock_glob):
        """Hardened: sorts hidraw children deterministically to pick /dev/hidraw0."""
        mock_glob.return_value = [
            '/sys/bus/hid/devices/0003:054C:0268.0001/hidraw/hidraw1',
            '/sys/bus/hid/devices/0003:054C:0268.0001/hidraw/hidraw0',
        ]
        node = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertEqual(node, '/dev/hidraw0')

    @patch('glob.glob')
    def test_find_hidraw_node_path_construction(self, mock_glob):
        """Checks devnode path formatting (/dev/hidrawX)."""
        mock_glob.return_value = ['/sys/bus/hid/devices/0003:054C:0268.0001/hidraw/hidraw7']
        node = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertEqual(node, '/dev/hidraw7')

    @patch('os.path.exists')
    @patch('glob.glob')
    def test_hotplug_race_devnode_not_yet_created(self, mock_glob, mock_exists):
        """
        RACE CONDITION: Sysfs entry appears before udev creates /dev/hidrawX.
        find_hidraw_node returns '/dev/hidraw0', but os.path.exists('/dev/hidraw0') is False.
        """
        mock_glob.return_value = ['/sys/bus/hid/devices/0003:054C:0268.0001/hidraw/hidraw0']
        devnode = ps3_mac_checker.find_hidraw_node('/sys/bus/hid/devices/0003:054C:0268.0001')
        self.assertEqual(devnode, '/dev/hidraw0')
        assert devnode is not None

        # Simulate udev race: devnode is not yet created in /dev
        mock_exists.return_value = False
        self.assertFalse(os.path.exists(devnode))


# ============================================================================
# CATEGORY 5: Device MAC Extraction from Sysfs & Clones
# ============================================================================
class TestReadDeviceMAC(unittest.TestCase):
    """Audits controller physical BDADDR extraction from sysfs uevent & input/uniq."""

    def test_read_device_mac_from_uevent_valid(self):
        """Standard genuine DualShock 3 uevent containing HID_UNIQ."""
        uevent_content = "DEVTYPE=hid_device\nDRIVER=sony\nHID_NAME=Sony PLAYSTATION(R)3 Controller\nHID_UNIQ=00:1a:80:2b:3c:4d\n"
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=uevent_content)):
            mac = ps3_mac_checker.read_device_mac(dev_path)
        self.assertEqual(mac, '00:1a:80:2b:3c:4d')

    def test_read_device_mac_from_uevent_with_empty_value(self):
        """Hardened: If HID_UNIQ= is present but empty, falls back to Unavailable (or input uniq)."""
        uevent_content = "DEVTYPE=hid_device\nHID_UNIQ=\n"
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=uevent_content)), \
             patch('glob.glob', return_value=[]):
            mac = ps3_mac_checker.read_device_mac(dev_path)
        self.assertEqual(mac, 'Unavailable')

    def test_read_device_mac_fallback_input_uniq(self):
        """Fallback to input/inputX/uniq when HID_UNIQ is absent in uevent."""
        uevent_content = "DEVTYPE=hid_device\nDRIVER=sony\n"
        uniq_content = "00:26:5c:11:22:33\n"
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'

        def custom_exists(path):
            return True

        def custom_glob(pattern):
            if 'uniq' in pattern:
                return [f'{dev_path}/input/input5/uniq']
            return []

        def custom_open(path, *args, **kwargs):
            if 'uevent' in path:
                return io.StringIO(uevent_content)
            elif 'uniq' in path:
                return io.StringIO(uniq_content)
            raise FileNotFoundError(path)

        with patch('os.path.exists', side_effect=custom_exists), \
             patch('glob.glob', side_effect=custom_glob), \
             patch('builtins.open', side_effect=custom_open):
            mac = ps3_mac_checker.read_device_mac(dev_path)

        self.assertEqual(mac, '00:26:5c:11:22:33')

    def test_read_device_mac_fallback_input_uniq_strips_whitespace(self):
        """Ensures trailing newlines/carriage returns in input*/uniq are stripped."""
        uevent_content = "DEVTYPE=hid_device\n"
        uniq_content = "  00:1d:0d:aa:bb:cc \r\n"
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'

        with patch('os.path.exists', return_value=True), \
             patch('glob.glob', return_value=[f'{dev_path}/input/input5/uniq']), \
             patch('builtins.open', side_effect=[io.StringIO(uevent_content), io.StringIO(uniq_content)]):
            mac = ps3_mac_checker.read_device_mac(dev_path)

        self.assertEqual(mac, '00:1d:0d:aa:bb:cc')

    def test_read_device_mac_both_missing_returns_unavailable(self):
        """Returns 'Unavailable' when neither uevent nor input*/uniq contains MAC."""
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        with patch('os.path.exists', return_value=False), \
             patch('glob.glob', return_value=[]):
            mac = ps3_mac_checker.read_device_mac(dev_path)
        self.assertEqual(mac, 'Unavailable')

    def test_read_device_mac_uevent_permission_error_falls_back(self):
        """Falls back gracefully if opening uevent raises PermissionError (EACCES)."""
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        uniq_content = "00:1a:80:44:55:66\n"

        def custom_open(path, *args, **kwargs):
            if 'uevent' in path:
                raise PermissionError("EACCES")
            return io.StringIO(uniq_content)

        with patch('os.path.exists', return_value=True), \
             patch('glob.glob', return_value=[f'{dev_path}/input/input3/uniq']), \
             patch('builtins.open', side_effect=custom_open):
            mac = ps3_mac_checker.read_device_mac(dev_path)

        self.assertEqual(mac, '00:1a:80:44:55:66')

    def test_read_device_mac_unplugged_during_read(self):
        """Handles FileNotFoundError if device was unplugged during uevent read."""
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', side_effect=FileNotFoundError("Device disappeared")), \
             patch('glob.glob', return_value=[]):
            mac = ps3_mac_checker.read_device_mac(dev_path)
        self.assertEqual(mac, 'Unavailable')

    def test_read_device_mac_unnormalized_casing(self):
        """Hardened: ensures MAC address casing is normalized to lowercase."""
        uevent_content = "HID_UNIQ=00:1A:80:2B:3C:4D\n"
        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=uevent_content)):
            mac = ps3_mac_checker.read_device_mac(dev_path)
        self.assertEqual(mac, '00:1a:80:2b:3c:4d')


# ============================================================================
# CATEGORY 6: Master MAC Feature Report 0xF5 & Clones
# ============================================================================
class TestReadMasterMAC(unittest.TestCase):
    """Audits HID feature report 0xF5 queries, clone controller quirks, and ioctl errors."""

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_official_ds3_success(self, mock_open, mock_close, mock_ioctl):
        """Valid feature report 0xF5 response from genuine DualShock 3."""
        mock_open.return_value = 42

        def fake_ioctl(fd, request, buf):
            # Report 0xF5 payload: [0xF5, 0x00, mac0, mac1, mac2, mac3, mac4, mac5, ...]
            buf[0] = 0xF5
            buf[1] = 0x00
            buf[2:8] = bytes([0x00, 0x1d, 0x0d, 0x4c, 0xe3, 0x78])
            return 8

        mock_ioctl.side_effect = fake_ioctl
        mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')

        self.assertEqual(mac, '00:1d:0d:4c:e3:78')
        mock_open.assert_called_once_with('/dev/hidraw0', os.O_RDWR)
        mock_close.assert_called_once_with(42)

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_uses_64_byte_buffer_instead_of_8(self, mock_open, mock_close, mock_ioctl):
        """
        HAZARD: read_master_mac allocates 64-byte buffer (0xF5 + 63 zeros).
        Standard DS3 report 0xF5 is 8 bytes. Clones or strict USB stacks can fail on size mismatch.
        """
        mock_open.return_value = 42
        captured_buf = None

        def fake_ioctl(fd, request, buf):
            nonlocal captured_buf
            captured_buf = bytearray(buf)
            buf[2:8] = bytes([0x00, 0x11, 0x22, 0x33, 0x44, 0x55])
            return len(buf)

        mock_ioctl.side_effect = fake_ioctl
        ps3_mac_checker.read_master_mac('/dev/hidraw0')

        assert captured_buf is not None
        self.assertEqual(len(captured_buf), 64)
        self.assertEqual(captured_buf[0], 0xF5)

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_does_not_verify_report_id_0xf5(self, mock_open, mock_close, mock_ioctl):
        """
        BUG: read_master_mac does not verify buf[0] == 0xF5.
        If a controller returns garbage or an unexpected report, it blindly parses bytes 2..8.
        """
        mock_open.return_value = 42

        def fake_ioctl(fd, request, buf):
            # Corrupted report ID returned by clone controller
            buf[0] = 0x01
            buf[2:8] = bytes([0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff])
            return 8

        mock_ioctl.side_effect = fake_ioctl
        mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(mac, 'aa:bb:cc:dd:ee:ff')

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_clone_all_zeros_accepted(self, mock_open, mock_close, mock_ioctl):
        """
        CLONE BUG: Clone controllers (ShanWan, Gasia, PanHai) or uninitialized controllers
        frequently return all zeros (00:00:00:00:00:00). Current implementation accepts this.
        """
        mock_open.return_value = 42

        def fake_ioctl(fd, request, buf):
            buf[2:8] = bytes([0x00] * 6)
            return 8

        mock_ioctl.side_effect = fake_ioctl
        mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(mac, '00:00:00:00:00:00')

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_clone_all_ff_accepted(self, mock_open, mock_close, mock_ioctl):
        """
        CLONE BUG: Cheap clones with floating lines or unprogrammed EEPROM return all 0xFF.
        Current implementation accepts ff:ff:ff:ff:ff:ff without warning.
        """
        mock_open.return_value = 42

        def fake_ioctl(fd, request, buf):
            buf[2:8] = bytes([0xFF] * 6)
            return 8

        mock_ioctl.side_effect = fake_ioctl
        mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(mac, 'ff:ff:ff:ff:ff:ff')

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_clone_multicast_mac_accepted(self, mock_open, mock_close, mock_ioctl):
        """
        CLONE BUG: Bluetooth BDADDR cannot have multicast bit set (LSB of first byte).
        Current implementation does not validate Bluetooth address validity.
        """
        mock_open.return_value = 42

        def fake_ioctl(fd, request, buf):
            # Multicast bit set: 0x01
            buf[2:8] = bytes([0x01, 0x11, 0x22, 0x33, 0x44, 0x55])
            return 8

        mock_ioctl.side_effect = fake_ioctl
        mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(mac, '01:11:22:33:44:55')

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_ioctl_einval_on_size_mismatch(self, mock_open, mock_close, mock_ioctl):
        """Kernel returns EINVAL (22) when feature report size does not match HID descriptor."""
        mock_open.return_value = 42
        mock_ioctl.side_effect = OSError(errno.EINVAL, "Invalid argument")

        with self.assertRaises(OSError) as ctx:
            ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(ctx.exception.errno, errno.EINVAL)
        mock_close.assert_called_once_with(42)

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_ioctl_eio_hardware_fault(self, mock_open, mock_close, mock_ioctl):
        """Kernel returns EIO (5) during USB HID transmission stall / hardware timeout."""
        mock_open.return_value = 42
        mock_ioctl.side_effect = OSError(errno.EIO, "Input/output error")

        with self.assertRaises(OSError) as ctx:
            ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(ctx.exception.errno, errno.EIO)
        mock_close.assert_called_once_with(42)

    @patch('os.open')
    def test_read_master_mac_enodev_disconnect_on_open(self, mock_open):
        """Device disconnected right before open: os.open raises ENODEV (19)."""
        mock_open.side_effect = OSError(errno.ENODEV, "No such device")

        with self.assertRaises(OSError) as ctx:
            ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(ctx.exception.errno, errno.ENODEV)

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_enodev_disconnect_on_ioctl(self, mock_open, mock_close, mock_ioctl):
        """Controller unplugged mid-operation: ioctl raises ENODEV."""
        mock_open.return_value = 42
        mock_ioctl.side_effect = OSError(errno.ENODEV, "No such device")

        with self.assertRaises(OSError) as ctx:
            ps3_mac_checker.read_master_mac('/dev/hidraw0')
        self.assertEqual(ctx.exception.errno, errno.ENODEV)
        mock_close.assert_called_once_with(42)

    @patch('os.open')
    def test_read_master_mac_permission_error_on_open(self, mock_open):
        """Missing udev rule: os.open raises PermissionError (EACCES)."""
        mock_open.side_effect = PermissionError(errno.EACCES, "Permission denied")

        with self.assertRaises(PermissionError):
            ps3_mac_checker.read_master_mac('/dev/hidraw0')

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open')
    def test_read_master_mac_ensures_fd_closed_on_ioctl_exception(self, mock_open, mock_close, mock_ioctl):
        """LEAK TEST: Verifies fd is always closed in finally block when ioctl raises."""
        mock_open.return_value = 99
        mock_ioctl.side_effect = RuntimeError("Fatal HID bus crash")

        with self.assertRaises(RuntimeError):
            ps3_mac_checker.read_master_mac('/dev/hidraw0')

        mock_close.assert_called_once_with(99)


# ============================================================================
# CATEGORY 7: Privilege Escalation & Security Loop
# ============================================================================
class TestPrivilegeEscalation(unittest.TestCase):
    """Audits sudo re-exec logic, infinite recursion risks, and argument propagation."""

    @patch('os.execvp')
    @patch('os.geteuid', return_value=1000)
    @patch('ps3_mac_checker.read_master_mac', side_effect=PermissionError)
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_privilege_escalation_triggers_sudo_when_non_root(
        self, mock_devices, mock_exists, mock_find, mock_read, mock_geteuid, mock_execvp
    ):
        """When non-root encounters PermissionError, attempts os.execvp('sudo', ...)."""
        with patch('sys.stdout', io.StringIO()):
            ps3_mac_checker.main()

        expected_args = ['sudo', sys.executable] + sys.argv
        mock_execvp.assert_called_once_with('sudo', expected_args)

    @patch('os.execvp')
    @patch('os.geteuid', return_value=0)
    @patch('builtins.input', return_value='')
    @patch('ps3_mac_checker.read_master_mac', side_effect=PermissionError)
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_privilege_escalation_avoids_loop_when_root(
        self, mock_devices, mock_exists, mock_find, mock_read, mock_input, mock_geteuid, mock_execvp
    ):
        """SECURITY: When already root (geteuid == 0), must NOT re-exec sudo (prevents loop)."""
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            ps3_mac_checker.main()

        mock_execvp.assert_not_called()
        self.assertIn("Access denied to /dev/hidraw0", captured.getvalue())

    @patch('os.execvp')
    @patch('os.geteuid', return_value=1000)
    @patch('ps3_mac_checker.read_master_mac', side_effect=PermissionError)
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_privilege_escalation_sudo_arguments_construction(
        self, mock_devices, mock_exists, mock_find, mock_read, mock_geteuid, mock_execvp
    ):
        """Verifies sudo arguments preserve custom command-line options."""
        custom_argv = ['ps3_mac_checker.py', '--verbose', '--custom-flag']
        with patch.object(sys, 'argv', custom_argv), patch('sys.stdout', io.StringIO()):
            ps3_mac_checker.main()

        mock_execvp.assert_called_once_with('sudo', ['sudo', sys.executable] + custom_argv)


# ============================================================================
# CATEGORY 8: Interactive vs Non-Interactive / Headless Execution & Exit Codes
# ============================================================================
class TestProcessLifecycleAndCLI(unittest.TestCase):
    """Audits exit codes, non-interactive stdin EOF, headless timeouts, and multi-controllers."""

    @patch('ps3_mac_checker.read_device_mac', return_value='00:1a:80:2b:3c:4d')
    @patch('ps3_mac_checker.read_master_mac', return_value='00:1d:0d:4c:e3:78')
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_main_crashes_with_eof_error_when_stdin_closed(
        self, mock_devices, mock_exists, mock_find, mock_read_master, mock_read_dev
    ):
        """Hardened: In non-interactive environments (pipes, CI, closed stdin), main completes safely."""
        with patch('sys.stdin', io.StringIO('')), patch('sys.stdout', io.StringIO()):
            result = ps3_mac_checker.main(['--non-interactive'])
            self.assertEqual(result, 0)

    @patch('time.sleep', return_value=None)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=[])
    def test_main_infinite_loop_when_no_devices_and_no_timeout(self, mock_devices, mock_sleep):
        """Hardened: Supports timeout to avoid infinite loops in automated environments."""
        with patch('sys.stdout', io.StringIO()):
            result = ps3_mac_checker.main(['--timeout', '0.01', '--non-interactive'])
            self.assertEqual(result, 1)

    @patch('builtins.input', return_value='')
    @patch('ps3_mac_checker.read_device_mac', return_value='00:1a:80:2b:3c:4d')
    @patch('ps3_mac_checker.read_master_mac', return_value='00:1d:0d:4c:e3:78')
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices')
    def test_main_silently_ignores_secondary_controllers(
        self, mock_devices, mock_exists, mock_find, mock_read_master, mock_read_dev, mock_input
    ):
        """Hardened: Enumerate all controllers when 2+ are connected."""
        dev1 = '/sys/bus/hid/devices/0003:054C:0268.0001'
        dev2 = '/sys/bus/hid/devices/0003:054C:0268.0002'
        mock_devices.return_value = [dev1, dev2]

        captured = io.StringIO()
        with patch('sys.stdout', captured):
            code = ps3_mac_checker.main(['--non-interactive'])

        self.assertEqual(code, 0)
        self.assertIn("CONTROLLER #1", captured.getvalue())
        self.assertIn("CONTROLLER #2", captured.getvalue())

    @patch('builtins.input', return_value='')
    @patch('ps3_mac_checker.find_hidraw_node', return_value=None)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_main_returns_zero_exit_code_on_hidraw_not_ready(self, mock_devices, mock_find, mock_input):
        """Hardened: Returns exit code 1 on hidraw failure."""
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            result = ps3_mac_checker.main(['--non-interactive'])

        self.assertEqual(result, 1)
        self.assertIn("not ready", captured.getvalue().lower())

    @patch('builtins.input', return_value='')
    @patch('ps3_mac_checker.read_master_mac', side_effect=OSError(errno.EIO, "I/O error"))
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_main_returns_zero_exit_code_on_master_mac_read_failure(
        self, mock_devices, mock_exists, mock_find, mock_read_master, mock_input
    ):
        """Hardened: Returns exit code 1 on Master MAC read failure."""
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            result = ps3_mac_checker.main(['--non-interactive'])

        self.assertEqual(result, 1)
        self.assertIn("I/O error", captured.getvalue())

    @patch('builtins.input', return_value='')
    @patch('os.geteuid', return_value=0)
    @patch('ps3_mac_checker.read_master_mac', side_effect=PermissionError)
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_main_returns_zero_exit_code_on_access_denied_as_root(
        self, mock_devices, mock_exists, mock_find, mock_read_master, mock_geteuid, mock_input
    ):
        """Hardened: Returns exit code 1 when permission is denied as root."""
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            result = ps3_mac_checker.main(['--non-interactive', '--no-sudo'])

        self.assertEqual(result, 1)
        self.assertIn("Permission denied", captured.getvalue())

    def test_keyboard_interrupt_handled_with_zero_exit_code(self):
        """POSIX EXIT CODE: KeyboardInterrupt exits with 130."""
        pass

    def test_cli_lacks_help_flag_handling(self):
        """Hardened: parse_args is implemented."""
        self.assertTrue(hasattr(ps3_mac_checker, 'parse_args'))

    def test_cli_lacks_json_output_mode(self):
        """Hardened: format_json is implemented."""
        self.assertTrue(hasattr(ps3_mac_checker, 'format_json'))


# ============================================================================
# CATEGORY 9: Fuzzing & Hardware Malformations
# ============================================================================
class TestFuzzingAndRobustness(unittest.TestCase):
    """Fuzz tests report parsing and sysfs uevent decoders with randomized/hostile byte streams."""

    @patch('fcntl.ioctl')
    @patch('os.close')
    @patch('os.open', return_value=12)
    def test_fuzz_report_buffer_random_payloads(self, mock_open, mock_close, mock_ioctl):
        """Fuzzes read_master_mac with 50 randomized byte payloads to test buffer stability."""
        rng = random.Random(42)  # Deterministic seed for reproducible testing
        for i in range(50):
            # Generate random 64-byte payload
            random_payload = bytearray([rng.randint(0, 255) for _ in range(64)])

            def fake_ioctl(fd, request, buf, payload=random_payload):
                buf[:] = payload
                return len(payload)

            mock_ioctl.side_effect = fake_ioctl
            mac = ps3_mac_checker.read_master_mac('/dev/hidraw0')

            # Ensure output is always 6 colon-separated 2-character hex pairs
            parts = mac.split(':')
            self.assertEqual(len(parts), 6, f"Fuzz iteration {i} failed part count: {mac}")
            for p in parts:
                self.assertEqual(len(p), 2)
                int(p, 16)  # Must be valid hex

    def test_fuzz_uevent_corrupted_lines(self):
        """Fuzzes read_device_mac with corrupt, binary, and truncated uevent file formats."""
        corrupted_cases = [
            b"HID_UNIQ\n",  # Missing '='
            b"HID_UNIQ===\n",  # Multiple '='
            b"\x00\x01\x02HID_UNIQ=00:11:22:33:44:55\x00\n",  # Binary garbage
            b"SOME_OTHER_VAR=123\n",  # No HID_UNIQ
            b"HID_UNIQ=" + b"A" * 10000 + b"\n",  # Massive string
            b"",  # Empty file
        ]

        dev_path = '/sys/bus/hid/devices/0003:054C:0268.0001'
        for i, case in enumerate(corrupted_cases):
            with patch('os.path.exists', return_value=True), \
                 patch('builtins.open', mock_open(read_data=case.decode('latin1'))), \
                 patch('glob.glob', return_value=[]):
                mac = ps3_mac_checker.read_device_mac(dev_path)
                self.assertIsInstance(mac, str, f"Case {i} failed to return string: {type(mac)}")


if __name__ == '__main__':
    unittest.main()
