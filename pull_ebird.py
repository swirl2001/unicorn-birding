"""Download daily eBird history for Presidio--Battery Godfrey (L999240).

For each date: the list of checklists (effort) and, when any exist, the species
reported that day. Saves one JSON file per date under data/raw/ so the pull can
resume if interrupted. Run: python3 pull_ebird.py 2016 2025
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import date, timedelta
from pathlib import Path

LOC = 'L999240'
ROOT = Path(__file__).parent
RAW = ROOT / 'data' / 'raw'
KEY = os.environ.get('EBIRD_API_KEY') or next(
    l.split('=', 1)[1].strip() for l in (ROOT / '.env').read_text().splitlines() if l.startswith('EBIRD_API_KEY='))


def get(path):
    for attempt in range(6):
        try:
            req = urllib.request.Request(f'https://api.ebird.org/v2/{path}', headers={'X-eBirdApiToken': KEY})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:  # eBird asks us to slow down: wait and try again
                time.sleep(60 * (attempt + 1))
                continue
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f'eBird kept refusing: {path}')


def main(y0, y1):
    RAW.mkdir(parents=True, exist_ok=True)
    d, end = date(y0, 1, 1), date(y1, 12, 31)
    done = 0
    while d <= end:
        out = RAW / f'{d.isoformat()}.json'
        if not out.exists():
            lists = get(f'product/lists/{LOC}/{d.year}/{d.month}/{d.day}?maxResults=200')
            obs = get(f'data/obs/{LOC}/historic/{d.year}/{d.month}/{d.day}?rank=mrec&detail=simple') if lists else []
            out.write_text(json.dumps(dict(date=d.isoformat(), lists=lists, obs=obs)))
            time.sleep(0.6)
            done += 1
            if done % 100 == 0:
                print(d.isoformat(), flush=True)
        d += timedelta(days=1)
    print('finished', y0, y1, flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]))
