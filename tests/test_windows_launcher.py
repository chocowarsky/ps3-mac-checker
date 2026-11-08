#!/usr/bin/env python3
"""
Unit tests for Windows Batch Launcher (ps3_mac_checker.bat)
Verifies file existence, argument forwarding, and Python fallback discovery logic.
"""

import os
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestWindowsBatchLauncher(unittest.TestCase):
    """Audits ps3_mac_checker.bat contents and structure."""

    def setUp(self):
        self.bat_path = os.path.join(REPO_ROOT, "ps3_mac_checker.bat")

    def test_bat_file_exists(self):
        self.assertTrue(os.path.isfile(self.bat_path))

    def test_bat_forwards_cli_arguments(self):
        with open(self.bat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("%*", content)
        self.assertIn("ps3_mac_checker.py", content)

    def test_bat_supports_py_launcher_fallback(self):
        with open(self.bat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("where python", content)
        self.assertIn("where py", content)

    def test_bat_preserves_exit_code(self):
        with open(self.bat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("exit /b %EXIT_CODE%", content)


if __name__ == '__main__':
    unittest.main()
