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

if command -v python3 >/dev/null 2>&1; then
    if [[ -f "${DIR}/ps3_mac_manager.py" ]]; then
        exec python3 "${DIR}/ps3_mac_manager.py" ${1+"$@"}
    elif [[ -f "${HOME}/.local/share/ps3-mac-manager/ps3_mac_manager.py" ]]; then
        exec python3 "${HOME}/.local/share/ps3-mac-manager/ps3_mac_manager.py" ${1+"$@"}
    fi
    echo "[!] Could not find ps3_mac_manager.py."
    read -r -p "Press [Enter] to exit..."
    exit 1
fi

echo "[!] Python 3 was not found on your Mac."
echo "    Install Xcode Command Line Tools (xcode-select --install) or Homebrew (brew install python3)."
read -r -p "Press [Enter] to exit..."
exit 1
