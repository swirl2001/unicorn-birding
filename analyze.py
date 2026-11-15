"""What makes a high-variety birding day at Battery Godfrey?

1. Daily species totals from eBird (data/raw/), excluding spuhs, slashes, hybrids and domestics.
2. Effort and season adjustment: species ~ log(checklists) + log(observers) + seasonal curve.
   The residual ("birdiness") says how much better than expected a day was.
3. Weather for each date from SFO airport (hourly) and Fort Point (wind, pressure).
4. Compares the best days against all other days in the same season.
Run: python3 analyze.py
"""
import csv, gzip, json, math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median

import numpy as np

ROOT = Path(__file__).parent
RAW, WX, OUT = ROOT / 'data' / 'raw', ROOT / 'data' / 'weather', ROOT / 'outputs'
OUT.mkdir(exist_ok=True)


def is_species(name):
    n = name.lower()
    return not (' sp.' in n or '/' in n or ' x ' in n or 'hybrid' in n or 'domestic' in n or '(' in n and 'type' in n)


# ---------- birds ----------
days = {}
for p in sorted(RAW.glob('*.json')):
    d = json.loads(p.read_text())
    if not d['lists']:
        continue
    species = {o['comName'] for o in d['obs'] if is_species(o['comName'])}
    observers = {l.get('userDisplayName') for l in d['lists']}
    days[d['date']] = dict(species=len(species), names=sorted(species), lists=len(d['lists']), observers=len(observers),
                           best_list=max((l.get('numSpecies') or 0) for l in d['lists']))
dates = sorted(days)
print(f'days with checklists: {len(dates)} ({dates[0]} to {dates[-1]})')

# ---------- effort + season model ----------
X, y = [], []
for ds in dates:
    d = days[ds]
    doy = date.fromisoformat(ds).timetuple().tm_yday / 365.25 * 2 * math.pi
    row = [1, math.log1p(d['lists']), math.log1p(d['observers'])]
    for k in (1, 2, 3):
        row += [math.sin(k * doy), math.cos(k * doy)]
    X.append(row); y.append(d['species'])
X, y = np.array(X), np.array(y, dtype=float)
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ beta
resid = y - pred
r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f'model R^2 (effort + season): {r2:.2f}')
for ds, p_, r in zip(dates, pred, resid):
    days[ds]['expected'] = round(float(p_), 1)
    days[ds]['birdiness'] = round(float(r), 1)

# ---------- weather ----------
def load_ftpc1():
    hours = defaultdict(lambda: defaultdict(list))
    for p in sorted(WX.glob('ftpc1h*.txt.gz')):
        with gzip.open(p, 'rt') as f:
            for line in f:
                if line.startswith('#'):
                    continue
                v = line.split()
                t = datetime(int(v[0]), int(v[1]), int(v[2]), int(v[3]))  # UTC
                if float(v[6]) < 99: hours[t]['wspd'].append(float(v[6]))
                if float(v[5]) < 999: hours[t]['wdir'].append(float(v[5]))
                if float(v[12]) < 9999: hours[t]['pres'].append(float(v[12]))
    return hours

sfo = defaultdict(list)  # local date -> hourly rows
with open(WX / 'ksfo_2016_2025.csv') as f:
    for r in csv.DictReader(f):
        t = datetime.strptime(r['valid'], '%Y-%m-%d %H:%M')  # local time
        sfo[t.date()].append((t, r))

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def circ_mean(degs):
    if not degs: return None
    s = sum(math.sin(math.radians(d)) for d in degs); c = sum(math.cos(math.radians(d)) for d in degs)
    return (math.degrees(math.atan2(s, c)) + 360) % 360

def wx_for(ds):
    d = date.fromisoformat(ds)
    prev = d - timedelta(days=1)
    night = [r for t, r in sfo.get(prev, []) if t.hour >= 20] + [r for t, r in sfo.get(d, []) if t.hour < 6]
    morning = [r for t, r in sfo.get(d, []) if 6 <= t.hour < 11]
    day = [r for t, r in sfo.get(d, []) if 6 <= t.hour < 18]
    prevday = sfo.get(prev, [])
    if not night or not morning:
        return None
    def wind(rows):
        dirs = [num(r['drct']) for r in rows if num(r['drct']) is not None and (num(r['sknt']) or 0) > 2]
        spd = [num(r['sknt']) for r in rows if num(r['sknt']) is not None]
        return circ_mean(dirs), (mean(spd) * 1.15078 if spd else None)  # knots -> mph
    nd, ns = wind(night)
    md, ms = wind(morning)
    vis = [num(r['vsby']) for r in morning if num(r['vsby']) is not None]
    rain_night = sum(num(r['p01i']) or 0 for r in night)
    rain_prev = sum(num(r['p01i']) or 0 for t, r in prevday)
    p_now = [num(r['mslp']) for r in morning if num(r['mslp'])]
    p_prev = [num(r['mslp']) for t, r in prevday if 6 <= t.hour < 11 and num(r['mslp'])]
    low_cloud = sum(1 for r in morning if r['skyc1'] in ('BKN', 'OVC') and (num(r['skyl1']) or 9999) <= 2000) / len(morning)
    temps = [num(r['tmpf']) for r in day if num(r['tmpf']) is not None]
    return dict(
        night_wind_dir=nd, night_wind_mph=ns, morning_wind_dir=md, morning_wind_mph=ms,
        morning_vis_mi=(min(vis) if vis else None), low_cloud_frac=low_cloud,
        rain_night_in=rain_night, rain_prevday_in=rain_prev,
        pressure_change_hpa=(mean(p_now) - mean(p_prev) if p_now and p_prev else None),
        max_temp_f=(max(temps) if temps else None),
    )

for ds in dates:
    days[ds].update(wx_for(ds) or {})

def season(ds):
    m = int(ds[5:7])
    return 'spring' if m in (3, 4, 5) else 'fall' if m in (8, 9, 10, 11) else 'summer' if m in (6, 7) else 'winter'

def sector(deg):
    if deg is None: return 'calm/var'
    return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][int(((deg + 22.5) % 360) // 45)]

# ---------- outputs ----------
fields = ['date', 'season', 'species', 'expected', 'birdiness', 'lists', 'observers', 'best_list',
          'night_wind_dir', 'night_wind_mph', 'morning_wind_dir', 'morning_wind_mph', 'morning_vis_mi',
          'low_cloud_frac', 'rain_night_in', 'rain_prevday_in', 'pressure_change_hpa', 'max_temp_f']
with (OUT / 'daily_birds_weather.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader()
    for ds in dates:
        w.writerow(dict(date=ds, season=season(ds), **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in days[ds].items() if k in fields}))

# Top days
by_raw = sorted(dates, key=lambda ds: -days[ds]['species'])[:15]
by_adj = sorted(dates, key=lambda ds: -days[ds]['birdiness'])[:15]
print('\nTop raw species days:')
for ds in by_raw:
    d = days[ds]; print(f"  {ds} {d['species']:3d} spp  lists {d['lists']:2d}  expected {d['expected']}")
print('\nTop effort-adjusted days (birdiness = species above expected):')
for ds in by_adj:
    d = days[ds]; print(f"  {ds} +{d['birdiness']:5.1f}  {d['species']} spp vs {d['expected']} expected, lists {d['lists']}, "
                       f"night wind {sector(d.get('night_wind_dir'))} {d.get('night_wind_mph') and round(d['night_wind_mph'])} mph, "
                       f"vis {d.get('morning_vis_mi')}, rain {d.get('rain_night_in')}")

# Weather contrast: top 5% birdiness vs rest, within fall and spring
summary = {'r2_effort_season': round(r2, 3), 'days': len(dates)}
for sea in ('fall', 'spring', 'winter'):
    ds_ = [ds for ds in dates if season(ds) == sea and days[ds].get('night_wind_mph') is not None]
    if len(ds_) < 40: continue
    cut = sorted(days[ds]['birdiness'] for ds in ds_)[int(len(ds_) * 0.9)]
    top = [days[ds] for ds in ds_ if days[ds]['birdiness'] >= cut]
    rest = [days[ds] for ds in ds_ if days[ds]['birdiness'] < cut]
    def share(rows, f): return round(sum(1 for r in rows if f(r)) / len(rows), 2)
    def med(rows, k): return round(median(r[k] for r in rows if r.get(k) is not None), 2)
    s = dict(n_top=len(top), n_rest=len(rest), cut=cut)
    for k in ('night_wind_mph', 'morning_wind_mph', 'morning_vis_mi', 'low_cloud_frac', 'pressure_change_hpa', 'max_temp_f'):
        s[k] = (med(top, k), med(rest, k))
    for name, f in [('night_wind_from_N_NE_E', lambda r: sector(r.get('night_wind_dir')) in ('N', 'NE', 'E')),
                    ('night_wind_from_S_SE', lambda r: sector(r.get('night_wind_dir')) in ('S', 'SE')),
                    ('night_wind_from_W_NW', lambda r: sector(r.get('night_wind_dir')) in ('W', 'NW')),
                    ('fog_morning_vis_lt_3', lambda r: (r.get('morning_vis_mi') or 10) < 3),
                    ('rain_overnight', lambda r: (r.get('rain_night_in') or 0) > 0.01),
                    ('rain_prev_day', lambda r: (r.get('rain_prevday_in') or 0) > 0.01),
                    ('pressure_rising', lambda r: (r.get('pressure_change_hpa') or 0) > 1)]:
        s[name] = (share(top, f), share(rest, f))
    summary[sea] = s
    print(f'\n{sea.upper()}: top 10% birdiness (n={len(top)}) vs rest (n={len(rest)}), shown as (top, rest)')
    for k, v in s.items():
        print(f'  {k}: {v}')

(OUT / 'summary.json').write_text(json.dumps(summary, indent=1))
months = defaultdict(list)
for ds in dates:
    months[int(ds[5:7])].append(days[ds]['species'])
print('\nMedian species by month:', {m: round(median(v)) for m, v in sorted(months.items())})
