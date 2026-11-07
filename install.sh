#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

echo "=== Installing PS3 Controller MAC Checker ==="

# 1. Install udev rule
echo "[*] Installing udev rule for non-root controller access..."
sudo cp "${DIR}/99-ps3-controller.rules" /etc/udev/rules.d/99-ps3-controller.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# 2. Make scripts executable
echo "[*] Setting file permissions..."
chmod +x "${DIR}/ps3_mac_checker.py" "${DIR}/ps3_mac_checker.sh"

# 3. Install desktop launcher
echo "[*] Installing desktop shortcut..."
mkdir -p "$HOME/.local/share/applications"
sed -e "s|/home/warsky/Arduino/check_ps3_mac.sh|${DIR}/ps3_mac_checker.sh|g" \
    "${DIR}/ps3-mac-checker.desktop" > "$HOME/.local/share/applications/ps3-mac-checker.desktop"
chmod +x "$HOME/.local/share/applications/ps3-mac-checker.desktop"

# Also install to ~/Arduino if folder exists
if [ -d "$HOME/Arduino" ]; then
    echo "[*] Adding shortcut to ~/Arduino..."
    cp -p "$HOME/.local/share/applications/ps3-mac-checker.desktop" "$HOME/Arduino/Check_PS3_MAC.desktop"
    gio set -t string "$HOME/Arduino/Check_PS3_MAC.desktop" metadata::trusted true 2>/dev/null || true
fi

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "=== Installation Complete! ==="
echo "You can now launch 'PS3 MAC Checker' from your application menu,"
echo "or double-click Check_PS3_MAC.desktop in ~/Arduino."
