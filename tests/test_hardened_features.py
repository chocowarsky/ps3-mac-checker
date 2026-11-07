#!/usr/bin/env python3
"""
Test Suite for Hardened Production Features of PS3 Controller MAC Address Checker
Covers CLI parsing, JSON formatting, timeout bounds, multi-controller enumeration,
clone MAC validation, safe non-interactive I/O, and POSIX exit codes.
"""

import sys
import os
import io
import json
import unittest
from unittest.mock import patch, MagicMock

# Add repo root to python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import ps3_mac_checker


class TestCLIArgumentParsing(unittest.TestCase):
    """Tests command line options and defaults."""

    def test_parse_args_defaults(self):
        args = ps3_mac_checker.parse_args([])
        self.assertFalse(args.json)
        self.assertFalse(args.non_interactive)
        self.assertIsNone(args.timeout)
        self.assertFalse(args.all)
        self.assertFalse(args.no_sudo)

    def test_parse_args_flags(self):
        args = ps3_mac_checker.parse_args(['-j', '-n', '-t', '5.5', '-a', '--no-sudo'])
        self.assertTrue(args.json)
        self.assertTrue(args.non_interactive)
        self.assertEqual(args.timeout, 5.5)
        self.assertTrue(args.all)
        self.assertTrue(args.no_sudo)


class TestSafeScreenClearing(unittest.TestCase):
    """Tests TTY and environment guards for ANSI escape codes."""

    @patch('sys.stdout.isatty', return_value=False)
    def test_clear_screen_suppressed_on_non_tty(self, mock_isatty):
        with patch('sys.stdout', io.StringIO()) as fake_out:
            ps3_mac_checker.clear_screen()
            self.assertEqual(fake_out.getvalue(), "")

    def test_clear_screen_emitted_on_interactive_tty(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            fake_out = io.StringIO()
            fake_out.isatty = lambda: True  # type: ignore
            with patch('sys.stdout', fake_out):
                ps3_mac_checker.clear_screen()
                self.assertEqual(fake_out.getvalue(), "\033[H\033[J")

    @patch('sys.stdout.isatty', return_value=True)
    def test_clear_screen_suppressed_when_no_color(self, mock_isatty):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            with patch('sys.stdout', io.StringIO()) as fake_out:
                ps3_mac_checker.clear_screen()
                self.assertEqual(fake_out.getvalue(), "")

    @patch('sys.stdout.isatty', return_value=True)
    def test_clear_screen_suppressed_on_dumb_term(self, mock_isatty):
        with patch.dict(os.environ, {"TERM": "dumb"}):
            with patch('sys.stdout', io.StringIO()) as fake_out:
                ps3_mac_checker.clear_screen()
                self.assertEqual(fake_out.getvalue(), "")


class TestCloneMACValidation(unittest.TestCase):
    """Tests detection of uninitialized or clone controller MAC address signatures."""

    def test_valid_genuine_mac(self):
        valid, warning = ps3_mac_checker.validate_mac("00:1d:0d:4c:e3:78")
        self.assertTrue(valid)
        self.assertIsNone(warning)

    def test_clone_all_zeros(self):
        valid, warning = ps3_mac_checker.validate_mac("00:00:00:00:00:00")
        self.assertFalse(valid)
        self.assertIsNotNone(warning)
        self.assertIn("all zeros", str(warning))

    def test_clone_all_ff(self):
        valid, warning = ps3_mac_checker.validate_mac("ff:ff:ff:ff:ff:ff")
        self.assertFalse(valid)
        self.assertIsNotNone(warning)
        self.assertIn("all 0xFF", str(warning))

    def test_multicast_mac_rejected(self):
        # 01:xx:xx:xx:xx:xx has lowest bit of first octet set (multicast)
        valid, warning = ps3_mac_checker.validate_mac("01:1d:0d:4c:e3:78")
        self.assertFalse(valid)
        self.assertIsNotNone(warning)
        self.assertIn("Multicast bit", str(warning))

    def test_malformed_mac(self):
        valid, warning = ps3_mac_checker.validate_mac("invalid_mac")
        self.assertFalse(valid)


class TestSafeInput(unittest.TestCase):
    """Tests non-interactive and closed-stdin input handling."""

    @patch('sys.stdin.isatty', return_value=False)
    def test_safe_input_does_not_prompt_on_non_tty(self, mock_isatty):
        self.assertEqual(ps3_mac_checker.safe_input("prompt"), "")

    @patch('sys.stdin.isatty', return_value=True)
    @patch('builtins.input', side_effect=EOFError)
    def test_safe_input_catches_eof(self, mock_input, mock_isatty):
        self.assertEqual(ps3_mac_checker.safe_input("prompt"), "")


class TestJSONFormatting(unittest.TestCase):
    """Tests JSON serialization."""

    def test_format_json(self):
        sample = [{"master_mac": "00:1d:0d:4c:e3:78", "device_mac": "a0:5a:5e:9b:aa:08"}]
        out = ps3_mac_checker.format_json(sample)
        parsed = json.loads(out)
        self.assertEqual(parsed[0]["master_mac"], "00:1d:0d:4c:e3:78")


class TestMainExecutionFlows(unittest.TestCase):
    """Tests end-to-end execution flows with new flags."""

    @patch('ps3_mac_checker.get_ps3_devices', return_value=[])
    def test_main_timeout_returns_code_1(self, mock_devices):
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            code = ps3_mac_checker.main(['--timeout', '0.01', '--non-interactive'])
        self.assertEqual(code, 1)
        self.assertIn("Timeout", captured.getvalue())

    @patch('ps3_mac_checker.get_ps3_devices', return_value=[])
    def test_main_json_timeout_returns_empty_list(self, mock_devices):
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            code = ps3_mac_checker.main(['--json', '--timeout', '0.01'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(captured.getvalue()), [])

    @patch('ps3_mac_checker.read_device_mac', return_value='a0:5a:5e:9b:aa:08')
    @patch('ps3_mac_checker.read_master_mac', return_value='00:1d:0d:4c:e3:78')
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=['/sys/bus/hid/devices/0003:054C:0268.0001'])
    def test_main_json_success(self, mock_devices, mock_exists, mock_find, mock_master, mock_dev):
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            code = ps3_mac_checker.main(['--json'])
        self.assertEqual(code, 0)
        data = json.loads(captured.getvalue())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["master_mac"], "00:1d:0d:4c:e3:78")
        self.assertTrue(data[0]["valid"])

    @patch('ps3_mac_checker.read_device_mac', return_value='a0:5a:5e:9b:aa:08')
    @patch('ps3_mac_checker.read_master_mac', return_value='00:1d:0d:4c:e3:78')
    @patch('ps3_mac_checker.find_hidraw_node', return_value='/dev/hidraw0')
    @patch('os.path.exists', return_value=True)
    @patch('ps3_mac_checker.get_ps3_devices', return_value=[
        '/sys/bus/hid/devices/0003:054C:0268.0001',
        '/sys/bus/hid/devices/0003:054C:0268.0002'
    ])
    def test_main_enumerates_multiple_controllers(
        self, mock_devices, mock_exists, mock_find, mock_master, mock_dev
    ):
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            code = ps3_mac_checker.main(['--non-interactive', '--all'])
        self.assertEqual(code, 0)
        self.assertIn("CONTROLLER #1", captured.getvalue())
        self.assertIn("CONTROLLER #2", captured.getvalue())


if __name__ == '__main__':
    unittest.main()
