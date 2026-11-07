#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# If executed outside a terminal (e.g. double-clicked from file manager):
if [ ! -t 1 ] && [ -z "$PS3_IN_TERMINAL" ]; then
    export PS3_IN_TERMINAL=1
    if command -v ptyxis >/dev/null 2>&1; then
        exec ptyxis -s --title "PS3 Controller MAC Checker" -- "$0" "$@"
    elif command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal --title "PS3 Controller MAC Checker" -- "$0" "$@"
    elif command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e "$0" "$@"
    fi
fi

python3 "${DIR}/ps3_mac_checker.py"
