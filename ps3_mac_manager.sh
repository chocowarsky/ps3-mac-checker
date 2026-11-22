#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "${SOURCE}" ]]; do
    LINK_TARGET="$(readlink "${SOURCE}")"
    if [[ "${LINK_TARGET}" == /* ]]; then
        SOURCE="${LINK_TARGET}"
    else
        LINK_DIR="$(cd -P "$(dirname "${SOURCE}")" >/dev/null 2>&1 && pwd)"
        SOURCE="${LINK_DIR}/${LINK_TARGET}"
    fi
done
DIR="$(cd -P "$(dirname "${SOURCE}")" >/dev/null 2>&1 && pwd)"

# If executed outside a terminal (e.g. double-clicked from file manager or app menu):
if [[ ! -t 1 && -z "${PS3_IN_TERMINAL:-}" ]]; then
    export PS3_IN_TERMINAL=1
    if [[ "$(uname -s)" == "Darwin" ]]; then
        open -a Terminal "$0"
        exit 0
    elif command -v ptyxis >/dev/null 2>&1; then
        exec ptyxis -s --title "PS3 Controller MAC Manager" -- "$0" ${1+"$@"}
    elif command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal --title "PS3 Controller MAC Manager" -- "$0" ${1+"$@"}
    elif command -v kgx >/dev/null 2>&1; then
        exec kgx --title "PS3 Controller MAC Manager" -- "$0" ${1+"$@"}
    elif command -v konsole >/dev/null 2>&1; then
        exec konsole -e "$0" ${1+"$@"}
    elif command -v xfce4-terminal >/dev/null 2>&1; then
        exec xfce4-terminal --title "PS3 Controller MAC Manager" -x "$0" ${1+"$@"}
    elif command -v mate-terminal >/dev/null 2>&1; then
        exec mate-terminal --title "PS3 Controller MAC Manager" -x "$0" ${1+"$@"}
    elif command -v tilix >/dev/null 2>&1; then
        exec tilix -e "$0" ${1+"$@"}
    elif command -v kitty >/dev/null 2>&1; then
        exec kitty --title "PS3 Controller MAC Manager" "$0" ${1+"$@"}
    elif command -v alacritty >/dev/null 2>&1; then
        exec alacritty --title "PS3 Controller MAC Manager" -e "$0" ${1+"$@"}
    elif command -v wezterm >/dev/null 2>&1; then
        exec wezterm start -- "$0" ${1+"$@"}
    elif command -v foot >/dev/null 2>&1; then
        exec foot --title "PS3 Controller MAC Manager" "$0" ${1+"$@"}
    elif command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e "$0" ${1+"$@"}
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -T "PS3 Controller MAC Manager" -e "$0" ${1+"$@"}
    fi
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] Python 3 is required. Install python3 with your package manager and try again."
    exit 1
fi

if [[ -f "${DIR}/ps3_mac_manager.py" ]]; then
    exec python3 "${DIR}/ps3_mac_manager.py" ${1+"$@"}
elif [[ -f "${HOME}/.local/share/ps3-mac-manager/ps3_mac_manager.py" ]]; then
    exec python3 "${HOME}/.local/share/ps3-mac-manager/ps3_mac_manager.py" ${1+"$@"}
else
    echo "[!] Could not find ps3_mac_manager.py in ${DIR}."
    exit 1
fi
