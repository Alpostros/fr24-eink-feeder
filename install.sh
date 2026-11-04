#!/bin/bash
[ "$(id -u)" -eq 0 ] || exec sudo -- bash "$0" "$@"
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=${1:-$HERE/config.env}
OPT=/opt/adsb-eink
WAVESHARE_SHA=d28b3c4cfc78eef1c6cd6e6e3013654e449d2864
ADSB_SCRIPTS_SHA=f933123935631da855a7f8a16c0cb7ad4eedca48

exec > >(tee -a /var/log/fr24-eink-install.log) 2>&1
export DEBIAN_FRONTEND=noninteractive

step() { echo; echo "=== $(date -Is) $*"; }
conf() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"\047 ' || true; }

step preflight
[ "$(uname -m)" = aarch64 ] || { echo "needs 64-bit Raspberry Pi OS (aarch64)"; exit 1; }
CODENAME=$(awk -F= '$1=="VERSION_CODENAME"{print $2}' /etc/os-release)
[ "$CODENAME" = trixie ] || echo "WARN: written for trixie, this is ${CODENAME:-unknown}"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE - copy config.env.example to config.env and fill it in"; exit 1; }
chmod 600 "$ENV_FILE"
FR24_KEY=$(conf FR24_KEY)
RX_LAT=$(conf RX_LAT)
RX_LON=$(conf RX_LON)
[ -n "$FR24_KEY" ] || FR24_KEY=$(sed -n 's/^fr24key="\(.*\)"$/\1/p' /etc/fr24feed.ini 2>/dev/null || true)

step packages
apt-get update
apt-get install -y wget ca-certificates python3-pil python3-numpy python3-spidev python3-gpiozero python3-lgpio fonts-dejavu-core

step e-ink display
raspi-config nonint do_spi 0
install -d "$OPT/waveshare_epd"
for f in __init__.py epdconfig.py epd2in13_V4.py; do
    wget -qO "$OPT/waveshare_epd/$f" "https://raw.githubusercontent.com/waveshareteam/e-Paper/$WAVESHARE_SHA/RaspberryPi_JetsonNano/python/lib/waveshare_epd/$f"
done
install -m 755 "$HERE/eink/adsb-eink.py" "$OPT/adsb-eink.py"
install -m 644 "$HERE/eink/adsb-eink.service" /etc/systemd/system/adsb-eink.service
id -u adsb-eink >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin adsb-eink
systemctl daemon-reload
systemctl enable adsb-eink

step dvb driver blacklist
printf 'blacklist %s\n' dvb_usb_rtl28xxu rtl2832_sdr rtl2832 rtl2830 > /etc/modprobe.d/blacklist-rtl-sdr.conf
modprobe -r dvb_usb_rtl28xxu rtl2832_sdr rtl2832 rtl2830 2>/dev/null || true

step readsb
if ! command -v readsb >/dev/null; then
    wget -qO /tmp/readsb-install.sh "https://raw.githubusercontent.com/wiedehopf/adsb-scripts/$ADSB_SCRIPTS_SHA/readsb-install.sh"
    bash /tmp/readsb-install.sh
fi
if [ -n "$RX_LAT" ] && [ -n "$RX_LON" ]; then
    /usr/local/bin/readsb-set-location "$RX_LAT" "$RX_LON"
else
    echo "WARN: RX_LAT/RX_LON not set - no receiver location; set it later with: sudo readsb-set-location LAT LON"
fi

step fr24feed
{
    echo 'receiver="beast-tcp"'
    [ -z "$FR24_KEY" ] || echo "fr24key=\"$FR24_KEY\""
    echo 'host="127.0.0.1:30005"'
    printf '%s="no"\n' bs raw mlat mlat-without-gps
} > /etc/fr24feed.ini
touch /etc/apt/sources.list
if ! dpkg-query -W -f='${Status}' fr24feed 2>/dev/null | grep -q 'install ok installed'; then
    wget -qO /tmp/fr24-install.sh https://fr24.com/install.sh
    bash /tmp/fr24-install.sh -a
fi
systemctl enable fr24feed
systemctl restart fr24feed

step start display
systemctl restart adsb-eink
sleep 20
systemctl is-active readsb fr24feed adsb-eink || true
fr24feed-status || true
echo
if [ -z "$FR24_KEY" ]; then
    echo "No FR24 sharing key yet: run 'sudo fr24feed --signup', then run this script again."
else
    echo "Done. Reboot once (sudo reboot) so the driver blacklist and SPI are applied from boot."
fi
