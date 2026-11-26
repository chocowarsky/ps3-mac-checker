"""Offline unit and CLI tests for ps3-mac-manager (no physical controller required)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import ps3_mac_manager as m  # noqa: E402


class TestMacUtilities(unittest.TestCase):
    def test_normalize_mac_all_supported_formats(self):
        expected = "00:1d:0d:4c:e3:78"
        samples = [
            "00:1D:0D:4C:E3:78",
            "00-1d-0d-4c-e3-78",
            "001d.0d4c.e378",
            "001d0d4ce378",
            "0x001d0d4ce378",
            "{0x00, 0x1d, 0x0d, 0x4c, 0xe3, 0x78}",
            "00 1d 0d 4c e3 78",
        ]
        for raw in samples:
            self.assertEqual(m.normalize_mac(raw), expected, f"failed for {raw!r}")

    def test_normalize_mac_rejects_invalid_inputs(self):
        for bad in ("", "not-a-mac", "00:11:22:33:44", "gg:11:22:33:44:55"):
            with self.assertRaises(ValueError):
                m.normalize_mac(bad)

    def test_generate_random_mac_is_locally_administered_unicast(self):
        for _ in range(25):
            mac = m.generate_random_mac()
            raw = m.mac_to_bytes(mac)
            self.assertEqual(len(raw), 6)
            self.assertEqual(raw[0] & 0x01, 0, f"multicast bit set in {mac}")
            self.assertEqual(raw[0] & 0x02, 0x02, f"locally administered bit unset in {mac}")
            self.assertTrue(m.validate_mac(mac))

    def test_validate_mac_for_write_blocks_unsafe_without_force(self):
        for bad in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:1d:0d:4c:e3:78"):
            with self.assertRaises(ValueError):
                m.validate_mac_for_write(bad, force=False)
            mac, warning = m.validate_mac_for_write(bad, force=True)
            self.assertEqual(mac, bad)
            self.assertTrue(bool(warning))

    def test_format_code_snippets_contains_esp32_begin_and_c_array(self):
        snippets = m.format_code_snippets("00:1d:0d:4c:e3:78")
        self.assertIn('Ps3.begin("00:1d:0d:4c:e3:78")', snippets["arduino"])
        self.assertIn("0x00", snippets["c_array"])


class TestOfflineCLI(unittest.TestCase):
    def _run_cli(self, *args: str, home_dir: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["HOME"] = home_dir
        env["XDG_CONFIG_HOME"] = str(Path(home_dir) / ".config")
        env["APPDATA"] = str(Path(home_dir) / "AppData")
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "ps3_mac_manager.py"), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_version_and_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = self._run_cli("--version", home_dir=tmp)
            self.assertEqual(v.returncode, 0)
            self.assertIn(m.__version__, v.stdout)

            h = self._run_cli("--help", home_dir=tmp)
            self.assertEqual(h.returncode, 0)
            self.assertIn("--doctor", h.stdout)

    def test_doctor_json_runs_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._run_cli("--doctor", "--json", home_dir=tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            payload = json.loads(res.stdout)
            self.assertEqual(payload["version"], m.__version__)
            self.assertIn("backend", payload)
            self.assertTrue(payload["python_ok"])

    def test_offline_profile_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            save = self._run_cli("--save-profile", "robot_alpha", "-s", "00:1d:0d:4c:e3:78", "-j", "-n", home_dir=tmp)
            self.assertEqual(save.returncode, 0, save.stderr)

            listed = self._run_cli("--list-profiles", "-j", "-n", home_dir=tmp)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            data = json.loads(listed.stdout)
            self.assertIn("robot_alpha", json.dumps(data))
            self.assertIn("00:1d:0d:4c:e3:78", json.dumps(data))

            deleted = self._run_cli("--delete-profile", "robot_alpha", "-j", "-n", home_dir=tmp)
            self.assertEqual(deleted.returncode, 0, deleted.stderr)


if __name__ == "__main__":
    unittest.main()
