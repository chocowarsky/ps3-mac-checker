#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

echo "=== Installing PS3 Controller MAC Manager ==="

# 1. Install udev rule
echo "[*] Installing udev rule for non-root controller read/write access..."
sudo cp "${DIR}/99-ps3-controller.rules" /etc/udev/rules.d/99-ps3-controller.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# 2. Make scripts executable
echo "[*] Setting file permissions..."
chmod +x "${DIR}/ps3_mac_manager.py" "${DIR}/ps3_mac_manager.sh"

# 3. Install desktop launcher and remove legacy checker entry
echo "[*] Installing desktop shortcut..."
mkdir -p "$HOME/.local/share/applications"
rm -f "$HOME/.local/share/applications/ps3-mac-checker.desktop"
sed -e "s|/home/warsky/Arduino/ps3_mac_manager.sh|${DIR}/ps3_mac_manager.sh|g" \
    "${DIR}/ps3-mac-manager.desktop" > "$HOME/.local/share/applications/ps3-mac-manager.desktop"
chmod +x "$HOME/.local/share/applications/ps3-mac-manager.desktop"

# 4. Sync to ~/Arduino if folder exists
if [[ -d "$HOME/Arduino" ]]; then
    echo "[*] Updating scripts and shortcut in ~/Arduino..."
    cp -p "${DIR}/ps3_mac_manager.py" "$HOME/Arduino/ps3_mac_manager.py"
    cp -p "${DIR}/ps3_mac_manager.sh" "$HOME/Arduino/ps3_mac_manager.sh"
    chmod +x "$HOME/Arduino/ps3_mac_manager.py" "$HOME/Arduino/ps3_mac_manager.sh"
    sed -e "s|/home/warsky/Arduino/ps3_mac_manager.sh|$HOME/Arduino/ps3_mac_manager.sh|g" \
        "${DIR}/ps3-mac-manager.desktop" > "$HOME/Arduino/PS3_MAC_Manager.desktop"
    chmod +x "$HOME/Arduino/PS3_MAC_Manager.desktop"
    gio set -t string "$HOME/Arduino/PS3_MAC_Manager.desktop" metadata::trusted true 2>/dev/null || true
    rm -f "$HOME/Arduino/Check_PS3_MAC.desktop" \
          "$HOME/Arduino/check_ps3_mac.py" \
          "$HOME/Arduino/check_ps3_mac.sh"
fi

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "=== Installation Complete! ==="
echo "You can now launch 'PS3 MAC Manager' from your application menu,"
echo "or double-click PS3_MAC_Manager.desktop in ~/Arduino."
