# GitHub Copilot Instructions (`ps3-mac-manager`)

`ps3-mac-manager` is a zero-dependency, 100% offline Python 3.8+ cross-platform CLI/TUI utility for managing Sony PS3 (DualShock 3 / Sixaxis) Bluetooth MAC addresses over USB.

- Read `AGENTS.md` and `skills/ps3-mac-manager/SKILL.md` before editing or running commands.
- Keep `ps3_mac_manager.py` strictly Python standard library only (no third-party runtime dependencies).
- Always pass `-j -n --no-sudo` when running CLI commands from non-interactive agent environments.
- Verify changes with `python3 -m unittest discover -s tests -v`.
