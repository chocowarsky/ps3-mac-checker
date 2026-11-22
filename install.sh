#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/chocowarsky/ps3-mac-manager.git"
ARCHIVE_URL="https://github.com/chocowarsky/ps3-mac-manager/archive/refs/heads/main.tar.gz"
DEFAULT_INSTALL_DIR="${HOME}/.local/share/ps3-mac-manager"
OS_NAME="$(uname -s)"

echo "=== Installing PS3 Controller MAC Manager (${OS_NAME}) ==="

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [[ -n "${SCRIPT_SOURCE}" && -f "${SCRIPT_SOURCE}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" >/dev/null 2>&1 && pwd)"
fi

if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/ps3_mac_manager.py" ]]; then
    INSTALL_DIR="${SCRIPT_DIR}"
    echo "[*] Using local repository at ${INSTALL_DIR}"
else
    INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
    echo "[*] Downloading PS3 MAC Manager to ${INSTALL_DIR}..."
    mkdir -p "$(dirname "${INSTALL_DIR}")"
    if command -v git >/dev/null 2>&1; then
        if [[ -d "${INSTALL_DIR}/.git" ]]; then
            git -C "${INSTALL_DIR}" pull --ff-only || true
        else
            rm -rf "${INSTALL_DIR}"
            git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
        fi
    elif command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
        TMP_DIR="$(mktemp -d)"
        trap 'rm -rf "${TMP_DIR}"' EXIT
        curl -fsSL "${ARCHIVE_URL}" -o "${TMP_DIR}/repo.tar.gz"
        tar -xzf "${TMP_DIR}/repo.tar.gz" -C "${TMP_DIR}"
        rm -rf "${INSTALL_DIR}"
        mv "${TMP_DIR}"/ps3-mac-manager-* "${INSTALL_DIR}"
    else
        echo "[!] Please install git or curl + tar first, then re-run this installer."
        exit 1
    fi
fi

# Verify Python 3.8+
if ! command -v python3 >/dev/null 2>&1; then
    echo "[*] Python 3 not found. Attempting installation..."
    if [[ "${OS_NAME}" == "Linux" ]]; then
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update && sudo apt-get install -y python3
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y python3
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -Sy --noconfirm python
        elif command -v zypper >/dev/null 2>&1; then
            sudo zypper install -y python3
        fi
    elif [[ "${OS_NAME}" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
        brew install python3
    fi
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] Python 3.8+ is required. Please install python3 and re-run."
    exit 1
fi

echo "[*] Setting file permissions..."
chmod +x "${INSTALL_DIR}/ps3_mac_manager.py" "${INSTALL_DIR}/ps3_mac_manager.sh" "${INSTALL_DIR}/ps3_mac_manager.command"

# Install global CLI command in ~/.local/bin
echo "[*] Installing 'ps3-mac-manager' CLI command into ${HOME}/.local/bin..."
mkdir -p "${HOME}/.local/bin"
ln -sf "${INSTALL_DIR}/ps3_mac_manager.py" "${HOME}/.local/bin/ps3-mac-manager"

if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
    # shellcheck disable=SC2016
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    for rc_file in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
        if [[ -f "${rc_file}" ]] && ! grep -Fq '.local/bin' "${rc_file}"; then
            printf '\n%s\n' "${PATH_LINE}" >> "${rc_file}"
            echo "[*] Added ~/.local/bin to PATH in ${rc_file}"
        fi
    done
    if [[ ! -f "${HOME}/.bashrc" && ! -f "${HOME}/.zshrc" ]]; then
        printf '%s\n' "${PATH_LINE}" >> "${HOME}/.profile"
        echo "[*] Added ~/.local/bin to PATH in ${HOME}/.profile"
    fi
fi

SKIP_UDEV=0
if [[ "${1:-}" == "--skip-udev" ]]; then
    SKIP_UDEV=1
fi

if [[ "${OS_NAME}" == "Linux" ]]; then
    if [[ "${SKIP_UDEV}" -eq 0 && -d "/etc/udev/rules.d" ]]; then
        if cmp -s "${INSTALL_DIR}/99-ps3-controller.rules" /etc/udev/rules.d/99-ps3-controller.rules 2>/dev/null; then
            echo "[✓] udev rule is already up to date."
        else
            echo "[*] Installing udev rule for non-root controller read/write access..."
            if sudo cp "${INSTALL_DIR}/99-ps3-controller.rules" /etc/udev/rules.d/99-ps3-controller.rules && \
               sudo udevadm control --reload-rules && \
               sudo udevadm trigger; then
                echo "[✓] udev rule installed successfully."
            else
                echo "[!] Could not install udev rule automatically. You can run with sudo or copy 99-ps3-controller.rules manually."
            fi
        fi
    fi

    echo "[*] Installing desktop launcher..."
    mkdir -p "${HOME}/.local/share/applications"
    rm -f "${HOME}/.local/share/applications/ps3-mac-checker.desktop"
    cat > "${HOME}/.local/share/applications/ps3-mac-manager.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PS3 MAC Manager
Comment=Read, Change, Pair & Manage PS3 Controller MAC Addresses for ESP32 / Arduino / PC
Exec="${INSTALL_DIR}/ps3_mac_manager.sh"
Icon=input-gaming
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
    chmod +x "${HOME}/.local/share/applications/ps3-mac-manager.desktop"
    update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
elif [[ "${OS_NAME}" == "Darwin" ]]; then
    if [[ -d "${HOME}/Desktop" ]]; then
        echo "[*] Installing macOS Desktop launcher..."
        ln -sf "${INSTALL_DIR}/ps3_mac_manager.command" "${HOME}/Desktop/PS3_MAC_Manager.command"
    fi
fi

# Sync to ~/Arduino if folder exists
if [[ -d "${HOME}/Arduino" ]]; then
    echo "[*] Updating scripts in ${HOME}/Arduino..."
    cp -p "${INSTALL_DIR}/ps3_mac_manager.py" "${HOME}/Arduino/ps3_mac_manager.py"
    cp -p "${INSTALL_DIR}/ps3_mac_manager.sh" "${HOME}/Arduino/ps3_mac_manager.sh"
    chmod +x "${HOME}/Arduino/ps3_mac_manager.py" "${HOME}/Arduino/ps3_mac_manager.sh"
    if [[ "${OS_NAME}" == "Linux" ]]; then
        cat > "${HOME}/Arduino/PS3_MAC_Manager.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PS3 MAC Manager
Comment=Read, Change, Pair & Manage PS3 Controller MAC Addresses for ESP32 / Arduino / PC
Exec="${HOME}/Arduino/ps3_mac_manager.sh"
Icon=input-gaming
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
        chmod +x "${HOME}/Arduino/PS3_MAC_Manager.desktop"
        gio set -t string "${HOME}/Arduino/PS3_MAC_Manager.desktop" metadata::trusted true 2>/dev/null || true
    fi
    rm -f "${HOME}/Arduino/Check_PS3_MAC.desktop" \
          "${HOME}/Arduino/check_ps3_mac.py" \
          "${HOME}/Arduino/check_ps3_mac.sh"
fi

echo ""
echo "=== Installation Complete! ==="
echo "Quick commands:"
echo "  ps3-mac-manager            # Launch interactive manager"
echo "  ps3-mac-manager --doctor   # Check drivers, udev/permissions & Bluetooth"
if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
    echo ""
    echo "[i] Open a new terminal (or run: export PATH=\"\$HOME/.local/bin:\$PATH\") to use 'ps3-mac-manager'."
fi
