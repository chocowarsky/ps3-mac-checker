#!/usr/bin/env python3
"""
Unit Tests for WindowsBackend (Win32 HID subsystem via ctypes)
Tests device enumeration, Master MAC (0xF5) and Device MAC (0xF2) extraction,
Win32 error handling, and resource cleanup using mock ctypes DLLs.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add repo root to python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import ps3_mac_checker


class TestWindowsBackend(unittest.TestCase):
    """Audits Windows Win32 HID implementation under mock ctypes environment."""

    def setUp(self):
        self.mock_setupapi = MagicMock()
        self.mock_hid = MagicMock()
        self.mock_kernel32 = MagicMock()
        self.backend = ps3_mac_checker.WindowsBackend(
            setupapi=self.mock_setupapi,
            hid=self.mock_hid,
            kernel32=self.mock_kernel32
        )

    def test_windows_backend_name(self):
        self.assertEqual(self.backend.name, "win32")

    def test_find_node_returns_same_path(self):
        path = r"\\?\hid#vid_054c&pid_0268#0001#{4d1e55b2-f16f-11cf-88cb-001111000030}"
        self.assertEqual(self.backend.find_node(path), path)

    def test_detect_devices_empty_when_no_hdevinfo(self):
        """Returns empty list when SetupDiGetClassDevsW fails."""
        self.mock_setupapi.SetupDiGetClassDevsW.return_value = -1
        devices = self.backend.detect_devices()
        self.assertEqual(devices, [])

    def test_read_master_mac_success(self):
        """Simulates successful Win32 CreateFileW and HidD_GetFeature report 0xF5."""
        self.mock_kernel32.CreateFileW.return_value = 1234  # valid handle

        def fake_get_feature(handle, c_buf, length):
            # Populate Report 0xF5: [0xF5, 0x00, mac0..mac5]
            c_buf[0] = 0xF5
            c_buf[1] = 0x00
            target_mac = [0x00, 0x1D, 0x0D, 0x4C, 0xE3, 0x78]
            for i, b in enumerate(target_mac):
                c_buf[2 + i] = b
            return True

        self.mock_hid.HidD_GetFeature.side_effect = fake_get_feature
        device_path = r"\\?\hid#vid_054c&pid_0268#0001"
        mac = self.backend.read_master_mac(device_path)

        self.assertEqual(mac, "00:1d:0d:4c:e3:78")
        self.mock_kernel32.CreateFileW.assert_called_once()
        self.mock_kernel32.CloseHandle.assert_called_once_with(1234)

    def test_read_master_mac_permission_denied(self):
        """Win32 ERROR_ACCESS_DENIED (5) raises PermissionError."""
        self.mock_kernel32.CreateFileW.return_value = -1
        self.mock_kernel32.GetLastError.return_value = 5  # ERROR_ACCESS_DENIED

        with self.assertRaises(PermissionError):
            self.backend.read_master_mac("dummy_path")

    def test_read_master_mac_device_disconnected(self):
        """Win32 ERROR_DEVICE_NOT_CONNECTED (1167) raises FileNotFoundError."""
        self.mock_kernel32.CreateFileW.return_value = -1
        self.mock_kernel32.GetLastError.return_value = 1167

        with self.assertRaises(FileNotFoundError):
            self.backend.read_master_mac("dummy_path")

    def test_read_master_mac_feature_report_failure_raises(self):
        """HidD_GetFeature returning FALSE raises OSError with Win32 error code."""
        self.mock_kernel32.CreateFileW.return_value = 1234
        self.mock_hid.HidD_GetFeature.return_value = False
        self.mock_kernel32.GetLastError.return_value = 31  # ERROR_GEN_FAILURE

        with self.assertRaises(OSError) as ctx:
            self.backend.read_master_mac("dummy_path")

        self.assertIn("31", str(ctx.exception))
        self.mock_kernel32.CloseHandle.assert_called_once_with(1234)

    def test_read_device_mac_success(self):
        """Simulates successful Win32 HidD_GetFeature report 0xF2 for Device MAC."""
        self.mock_kernel32.CreateFileW.return_value = 5678

        def fake_get_feature(handle, c_buf, length):
            c_buf[0] = 0xF2
            device_mac = [0xA0, 0x5A, 0x5E, 0x9B, 0xAA, 0x08]
            for i, b in enumerate(device_mac):
                c_buf[4 + i] = b
            return True

        self.mock_hid.HidD_GetFeature.side_effect = fake_get_feature
        device_path = r"\\?\hid#vid_054c&pid_0268#0001"
        mac = self.backend.read_device_mac(device_path)

        self.assertEqual(mac, "a0:5a:5e:9b:aa:08")
        self.mock_kernel32.CloseHandle.assert_called_once_with(5678)

    def test_read_device_mac_failure_returns_unavailable(self):
        """When CreateFileW fails, read_device_mac returns 'Unavailable' gracefully."""
        self.mock_kernel32.CreateFileW.return_value = -1
        mac = self.backend.read_device_mac("dummy_path")
        self.assertEqual(mac, "Unavailable")


class TestWindowsEndToEndInspection(unittest.TestCase):
    """Tests inspect_controller and main flow using WindowsBackend."""

    @patch('ps3_mac_checker.safe_input', return_value='')
    def test_inspect_controller_with_windows_backend(self, mock_input):
        backend = MagicMock(spec=ps3_mac_checker.WindowsBackend)
        backend.name = "win32"
        backend.find_node.side_effect = lambda p: p
        backend.read_master_mac.return_value = "00:1d:0d:4c:e3:78"
        backend.read_device_mac.return_value = "a0:5a:5e:9b:aa:08"

        dev_path = r"\\?\hid#vid_054c&pid_0268#0001"
        result = ps3_mac_checker.inspect_controller(dev_path, backend=backend)

        self.assertEqual(result["master_mac"], "00:1d:0d:4c:e3:78")
        self.assertEqual(result["device_mac"], "a0:5a:5e:9b:aa:08")
        self.assertTrue(result["valid"])
        self.assertIsNone(result["error"])


if __name__ == '__main__':
    unittest.main()
