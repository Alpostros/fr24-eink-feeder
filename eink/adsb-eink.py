#!/usr/bin/python3
import argparse
import json
import math
import os
import signal
import sys
import time
import urllib.request
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

W, H = 250, 122
INTERVAL = 60
FULL_EVERY = 30
SAVE_EVERY = 10
MONITOR = 'http://127.0.0.1:8754/monitor.json'
FONT_DIR = os.environ.get('ADSB_EINK_FONT_DIR', '/usr/share/fonts/truetype/dejavu')
COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def monitor():
    try:
        with urllib.request.urlopen(MONITOR, timeout=3) as r:
            return json.load(r)
    except (OSError, ValueError):
        return {}


def distance_bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    km = 6371.0 * 2 * math.asin(math.sqrt(a))
    deg = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                  math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
    return km, COMPASS[int(((deg + 360) % 360 + 22.5) // 45) % 8]


def altitude(ac):
    alt = ac.get('alt_baro', ac.get('alt_geom'))
    if alt == 'ground':
        return 'GND'
    if not isinstance(alt, (int, float)):
        return ''
    return f'FL{round(alt / 100):03d}' if alt >= 10000 else f'{int(alt)} ft'


class Today:
    def __init__(self, path):
        self.path = path
        s = load(path) if path else {}
        self.day = s.get('day')
        self.seen = set(s.get('seen', []))
        self.max_km = s.get('max_km', 0.0)

    def roll(self):
        today = date.today().isoformat()
        if self.day != today:
            self.day, self.seen, self.max_km = today, set(), 0.0

    def save(self):
        if not self.path:
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'day': self.day, 'seen': sorted(self.seen), 'max_km': self.max_km}, f)
        os.replace(tmp, self.path)


def snapshot(readsb_dir, today):
    doc = load(os.path.join(readsb_dir, 'aircraft.json'))
    rx = load(os.path.join(readsb_dir, 'receiver.json'))
    last1 = load(os.path.join(readsb_dir, 'stats.json')).get('last1min', {})
    aircraft = [a for a in doc.get('aircraft', []) if a.get('seen', 0) < 60]
    with_pos = [a for a in aircraft if 'lat' in a and 'lon' in a and a.get('seen_pos', 0) < 60]

    today.roll()
    today.seen.update(a['hex'] for a in aircraft if 'hex' in a)

    nearest = None
    if 'lat' in rx and 'lon' in rx:
        for a in with_pos:
            km, brg = distance_bearing(rx['lat'], rx['lon'], a['lat'], a['lon'])
            today.max_km = max(today.max_km, km)
            if nearest is None or km < nearest[0]:
                nearest = (km, brg, a)

    span = last1.get('end', 0) - last1.get('start', 0)
    rate = last1['messages'] / span if span > 0 and 'messages' in last1 else None

    mon = monitor()
    return {
        'total': len(aircraft),
        'with_pos': len(with_pos),
        'rate': rate,
        'today': len(today.seen),
        'max_km': today.max_km,
        'nearest': nearest,
        'alias': mon.get('feed_alias', '?'),
        'status': mon.get('feed_status', 'down'),
    }


def font(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.load_default(size)


def render(s, flip=False):
    img = Image.new('1', (W, H), 255)
    d = ImageDraw.Draw(img)
    small, bold, mid, big = (font('DejaVuSans.ttf', 11), font('DejaVuSans-Bold.ttf', 12),
                             font('DejaVuSans-Bold.ttf', 15), font('DejaVuSans-Bold.ttf', 34))

    d.text((3, 2), f"FR24 {s['alias']}", font=bold, fill=0)
    online = s['status'] == 'connected'
    right = f"{'●' if online else '○'} {'online' if online else s['status']}  {datetime.now():%H:%M}"
    d.text((W - 3 - d.textlength(right, font=small), 3), right, font=small, fill=0)
    d.line((0, 18, W, 18), fill=0)

    d.text((4, 19), str(s['total']), font=big, fill=0)
    d.text((5, 60), f"aircraft · {s['with_pos']} with pos", font=small, fill=0)

    rows = [
        ('–' if s['rate'] is None else f"{s['rate']:.0f}", 'msg/s'),
        (str(s['today']), 'today'),
        (f"{s['max_km']:.0f}", 'km max'),
    ]
    for i, (value, label) in enumerate(rows):
        y = 21 + i * 18
        d.text((150, y), value, font=mid, fill=0)
        d.text((154 + d.textlength(value, font=mid), y + 4), label, font=small, fill=0)

    d.line((0, 78, W, 78), fill=0)
    d.text((3, 80), 'nearest', font=small, fill=0)
    if s['nearest']:
        km, brg, a = s['nearest']
        name = (a.get('flight') or a.get('hex', '?')).strip().upper()
        line = f"{name}  {altitude(a)}  {km:.0f} km  {brg}"
    else:
        line = 'no positions yet'
    size = 15
    while size > 10 and d.textlength(line, font=font('DejaVuSans-Bold.ttf', size)) > W - 6:
        size -= 1
    d.text((3, 96), line, font=font('DejaVuSans-Bold.ttf', size), fill=0)

    return img.rotate(180) if flip else img


def sleep_to_next_tick():
    time.sleep(INTERVAL - time.time() % INTERVAL)


def run(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from waveshare_epd import epd2in13_V4

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    epd = epd2in13_V4.EPD()
    today = Today(args.state)
    frame = 0
    epd.init()
    epd.Clear(0xFF)
    try:
        while True:
            buf = epd.getbuffer(render(snapshot(args.readsb_dir, today), args.flip))
            if frame % FULL_EVERY == 0:
                if frame:
                    epd.sleep()
                    epd.init()
                epd.displayPartBaseImage(buf)
            else:
                epd.displayPartial(buf)
            if frame % SAVE_EVERY == 0:
                today.save()
            frame += 1
            sleep_to_next_tick()
    finally:
        today.save()
        epd.sleep()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--readsb-dir', default='/run/readsb')
    p.add_argument('--state', default='/var/lib/adsb-eink/today.json')
    p.add_argument('--flip', action='store_true')
    p.add_argument('--png', help='render one frame to this file and exit, without touching the panel')
    args = p.parse_args()
    if args.png:
        render(snapshot(args.readsb_dir, Today(None)), args.flip).save(args.png)
        return
    run(args)


if __name__ == '__main__':
    main()
