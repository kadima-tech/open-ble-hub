#!/usr/bin/env bash
# Install or update Philips BLE Hub on a Raspberry Pi (DietPi or Raspberry Pi OS).
# Run from the repository root:  sudo ./deploy/install.sh
set -euo pipefail

APP_DIR=/opt/philips-ble-hub
DATA_DIR=/var/lib/philips-ble-hub
SERVICE_USER=philips-ble-hub
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

echo "==> Packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-dev build-essential bluez rsync >/dev/null

echo "==> Service user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
getent group bluetooth >/dev/null || groupadd --system bluetooth
usermod -aG bluetooth "$SERVICE_USER"

echo "==> Application files in $APP_DIR"
mkdir -p "$APP_DIR" "$DATA_DIR"
rsync -a --delete --exclude '__pycache__' "$SRC_DIR/philips_ble" "$SRC_DIR/ble_hub" "$SRC_DIR/requirements.txt" "$APP_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

echo "==> Python environment"
[[ -x "$APP_DIR/.venv/bin/python" ]] || python3 -m venv "$APP_DIR/.venv"
PIP_ARGS=(-q)
case "$(uname -m)" in
  armv6l|armv7l) PIP_ARGS+=(--extra-index-url https://www.piwheels.org/simple) ;;
esac
"$APP_DIR/.venv/bin/pip" install "${PIP_ARGS[@]}" --upgrade pip
"$APP_DIR/.venv/bin/pip" install "${PIP_ARGS[@]}" -r "$APP_DIR/requirements.txt"

echo "==> systemd unit"
install -m 644 "$SRC_DIR/deploy/philips-ble-hub.service" /etc/systemd/system/philips-ble-hub.service
systemctl daemon-reload
systemctl enable --now bluetooth >/dev/null 2>&1 || true
systemctl enable philips-ble-hub >/dev/null
systemctl restart philips-ble-hub

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
echo "Philips BLE Hub is running. Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080 in a browser on the same network."
