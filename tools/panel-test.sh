#!/bin/bash
[ "$(id -u)" -eq 0 ] || exec sudo -- bash "$0" "$@"
set -uo pipefail

systemctl stop adsb-eink
cd /tmp || exit 1
timeout 90 python3 - <<'EOF'
import logging
import sys

logging.basicConfig(level=logging.DEBUG, format='%(relativeCreated)6d ms %(message)s')
sys.path.insert(0, '/opt/adsb-eink')
from waveshare_epd import epd2in13_V4

epd = epd2in13_V4.EPD()
epd.init()
epd.Clear(0x00)
epd.sleep()
EOF
echo "exit $?"
systemctl start adsb-eink
