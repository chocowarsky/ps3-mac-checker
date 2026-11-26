# CLAUDE.md

Read [AGENTS.md](AGENTS.md) and [skills/ps3-mac-manager/SKILL.md](skills/ps3-mac-manager/SKILL.md) before running or modifying `ps3-mac-manager`.

- **Zero-dependency, 100% offline Python 3.8+ CLI** (no API keys, no pip installs needed).
- **Agent invocation rule:** Always pass `-j -n --no-sudo` (`--json --non-interactive --no-sudo`) so commands never block on interactive menus or `sudo` prompts.
- **Diagnostics:** `python3 ps3_mac_manager.py --doctor --json`
- **Tests:** `python3 -m unittest discover -s tests -v`
