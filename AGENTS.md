# AGENTS.md — `ps3-mac-manager`

Universal instructions for **every AI agent harness** (Antigravity, Claude Code, OpenAI Codex, Cursor, Windsurf, VS Code / GitHub Copilot, OpenCode, Cline, Roo Code, Amp, Goose, Hermes) running, testing, or modifying `ps3-mac-manager`.

## 1. Architecture & Offline Posture

- **100% offline, zero external Python dependencies** (`Python >= 3.8` stdlib only; single module `ps3_mac_manager.py`).
- **Zero API keys or credentials required.** No network calls are ever made by `ps3_mac_manager.py`.
- Local profiles and automatic MAC backups are stored privately in `~/.config/ps3-mac-manager/config.json` (Linux/macOS) or `%APPDATA%\ps3-mac-manager\config.json` (Windows).
- Native OS backends via `ctypes`/stdlib:
  - Windows: `hid.dll`, `setupapi.dll`, `kernel32.dll`, `bthprops.cpl`
  - macOS: `IOKit.framework`, `CoreFoundation.framework`
  - Linux: `/dev/hidraw*` (`HIDIOCGFEATURE` / `HIDIOCSFEATURE`), `sysfs`, `/sys/class/bluetooth/hci*/address`

## 2. Hard Agent Execution Rules

1. **Always pass `-j -n --no-sudo` (`--json --non-interactive --no-sudo`)** when invoking from an agent shell so the CLI never blocks on TUI prompts or `sudo` password entry.
2. **Start with read-only diagnostics:** Run `python3 ps3_mac_manager.py --doctor --json` before any hardware action.
3. **Never write to controller EEPROM without explicit user request** (`-s`, `-g`, `-p`, `--apply-profile`, `--clone`, `--restore`). Never pass `--force` unless explicitly instructed.
4. **Never run `sudo` silently:** If Linux lacks `/etc/udev/rules.d/99-ps3-controller.rules`, advise the user to run `./install.sh` once or run with `sudo` themselves.

## 3. Running & Testing

```bash
# Offline diagnostics (no controller required)
python3 ps3_mac_manager.py --doctor --json

# Read-only check for plugged-in PS3 controllers
python3 ps3_mac_manager.py --check -j -n -t 0 --no-sudo

# Manage profiles offline
python3 ps3_mac_manager.py --list-profiles -j -n

# Run automated offline test suite (no hardware required)
python3 -m unittest discover -s tests -v
```

## 4. Full Skill Specification

For the complete command matrix and OS troubleshooting guide, read [skills/ps3-mac-manager/SKILL.md](skills/ps3-mac-manager/SKILL.md).
