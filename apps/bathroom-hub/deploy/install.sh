#!/usr/bin/env bash
# Install Bathroom Hub on a Raspberry Pi (DietPi or Raspberry Pi OS), or update
# it to this checkout. Run from a copy of the repository:
#   sudo ./apps/bathroom-hub/deploy/install.sh
# Later updates and rollbacks: sudo hub-update update bathroom-hub (deploy/README.md).
set -euo pipefail

APP_DIR=/opt/bathroom-hub
DATA_DIR=/var/lib/bathroom-hub
SERVICE_USER=bathroom-hub
# Earlier names of this service, newest first.
OLD_NAMES=(open-ble-hub philips-ble-hub)
HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$HUB_DIR/../.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

echo "==> Packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-dev build-essential bluez git >/dev/null

# Keep the data of an install under an earlier name and drop the rest. The hub
# renames open-ble-hub.db or philips-ble-hub.db itself on start.
for old in "${OLD_NAMES[@]}"; do
  if [[ -f /etc/systemd/system/$old.service || -d /var/lib/$old ]]; then
    echo "==> Moving $old to bathroom-hub"
    systemctl disable --now "$old" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$old.service"
    systemctl daemon-reload
    if [[ -d /var/lib/$old && ! -e $DATA_DIR ]]; then
      mv "/var/lib/$old" "$DATA_DIR"
    fi
    rm -rf "/opt/$old"
    if id -u "$old" >/dev/null 2>&1; then
      userdel "$old" || true
    fi
  fi
done

echo "==> Service user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
getent group bluetooth >/dev/null || groupadd --system bluetooth
usermod -aG bluetooth "$SERVICE_USER"
mkdir -p "$APP_DIR" "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

systemctl enable --now bluetooth >/dev/null 2>&1 || true

echo "==> hub-update"
install -m 755 "$REPO_DIR/deploy/hub_update.py" /usr/local/sbin/hub-update
# Builds a release of this checkout in $APP_DIR/releases, switches the service
# to it, and rolls back if it does not come up healthy. The libraries come from
# this checkout too, so the Pi runs the same code as the repository.
/usr/local/sbin/hub-update update bathroom-hub --source "$REPO_DIR"
# Installs from before hub-update kept one virtualenv here.
rm -rf "$APP_DIR/.venv"

echo "==> Checks"
for cfg in /boot/firmware/config.txt /boot/config.txt; do
  if [[ -f "$cfg" ]] && grep -Eq '^\s*dtoverlay=disable-bt' "$cfg"; then
    echo "WARNING: $cfg disables the built-in Bluetooth (dtoverlay=disable-bt)."
    echo "         On DietPi enable it with: dietpi-config > Advanced Options > Bluetooth, then reboot."
  fi
done
if ! systemctl is-active --quiet bluetooth; then
  echo "WARNING: bluetooth.service is not running. Enable Bluetooth and reboot."
fi
if [[ "$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)" == "UTC" ]]; then
  echo "NOTE: the timezone is UTC. Weighs use the Pi's local time, so set it (dietpi-config > Language/Regional Options > Timezone)."
fi

echo
echo "Bathroom Hub is running. Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080 in a browser on the same network."
