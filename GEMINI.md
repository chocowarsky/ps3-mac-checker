# GEMINI.md

Instructions for Antigravity (AGY) and Gemini CLI agents using `ps3-mac-manager`.

- **Canonical skill:** [skills/ps3-mac-manager/SKILL.md](skills/ps3-mac-manager/SKILL.md)
- **Universal agent guide:** [AGENTS.md](AGENTS.md)
- **Offline diagnostics:** `python3 ps3_mac_manager.py --doctor --json`
- **Non-interactive agent rule:** Always pass `-j -n --no-sudo`; never modify controller EEPROM without explicit user confirmation.
- **Tests:** `python3 -m unittest discover -s tests -v`
