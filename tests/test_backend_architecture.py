#!/usr/bin/env python3
"""
Tests for Backend Architecture & Factory
Verifies BaseBackend, LinuxBackend, WindowsBackend abstraction and platform selection.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add repo root to python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import ps3_mac_checker


class TestBackendArchitecture(unittest.TestCase):
    """Verifies backend abstraction layer and get_backend factory."""

    def test_get_backend_linux_returns_linux_backend(self):
        backend = ps3_mac_checker.get_backend('linux')
        self.assertIsInstance(backend, ps3_mac_checker.LinuxBackend)
        self.assertEqual(backend.name, 'linux')

    def test_get_backend_win32_returns_windows_backend(self):
        backend = ps3_mac_checker.get_backend('win32')
        self.assertIsInstance(backend, ps3_mac_checker.WindowsBackend)
        self.assertEqual(backend.name, 'win32')

    def test_base_backend_interface_methods(self):
        """Verifies abstract methods exist on BaseBackend."""
        base = ps3_mac_checker.BaseBackend()
        with self.assertRaises(NotImplementedError):
            base.detect_devices()
        with self.assertRaises(NotImplementedError):
            base.read_master_mac('dummy')
        with self.assertRaises(NotImplementedError):
            base.read_device_mac('dummy')

    def test_linux_backend_methods_delegation(self):
        """Verifies LinuxBackend provides required methods."""
        backend = ps3_mac_checker.LinuxBackend()
        self.assertTrue(callable(backend.detect_devices))
        self.assertTrue(callable(backend.read_master_mac))
        self.assertTrue(callable(backend.read_device_mac))

    def test_windows_backend_methods_delegation(self):
        """Verifies WindowsBackend provides required methods."""
        backend = ps3_mac_checker.WindowsBackend()
        self.assertTrue(callable(backend.detect_devices))
        self.assertTrue(callable(backend.read_master_mac))
        self.assertTrue(callable(backend.read_device_mac))


if __name__ == '__main__':
    unittest.main()
