"""Lead-up analysis: do the 1-3 days BEFORE a big birding day share a weather pattern?

Reuses analyze.py's local weather (Fort Point wind/pressure/temperature, rain at Battery Godfrey) for the days
before each birded date, compares the top 10% days (effort- and season-adjusted) with the rest by season, then tests
whether lead-up features improve the cross-validated forecast model.
Run: python3 leadup.py   (writes outputs/leadup.json and prints a report)
"""
import contextlib, io, json, math, runpy
from datetime import date, timedelta
from pathlib import Path
from statistics import median
import numpy as np

ROOT = Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):
    A = runpy.run_path(str(ROOT / 'analyze.py'))
days, wx_for, sector = A['days'], A['wx_for'], A['sector']
OFF, SOUTH = ('N', 'NE', 'E'), ('SE', 'S', 'SW')
cache = {}
def W(d):
    k = d.isoformat()
    if k not in cache:
        cache[k] = wx_for(k) or {}
    return cache[k]

def leadup(ds):
    d = date.fromisoformat(ds)
    w0, prev = W(d), [W(d - timedelta(days=i)) for i in (1, 2, 3)]
    if not w0 or any(not p for p in prev):
        return None
    sec = lambda w: sector(w.get('night_wind_dir')) if w.get('night_wind_mph') is not None else None
    temps = [p.get('max_temp_f') for p in prev if p.get('max_temp_f') is not None]
    pres = [p.get('pressure_change_hpa') for p in prev]
    return dict(
        rain_prev3_in=sum(p.get('rain_night_in') or 0 for p in prev),           # rain on the 3 nights before
        rain_then_clear=float(sum(p.get('rain_night_in') or 0 for p in prev) > 0.05 and (w0.get('rain_night_in') or 0) < 0.01),
        offshore_switch=float(sec(w0) in OFF and sec(prev[0]) not in OFF),      # first offshore night after onshore
        south_prev2=float(sum(sec(p) in SOUTH for p in prev[:2]) >= 1),         # south wind one of the two nights before
        pressure_3d_hpa=(sum(x for x in pres if x is not None) if all(x is not None for x in pres) else None),
        warmup_f=(w0['max_temp_f'] - sum(temps) / len(temps)) if temps and w0.get('max_temp_f') is not None else None,
        calm_prev3=float(sum((p.get('night_wind_mph') or 99) < 5 for p in prev)),
    )

rows = []
for ds, d in days.items():
    if d.get('birdiness') is None:
        continue
    L = leadup(ds)
    if L:
        rows.append(dict(date=ds, season=A['season'](ds), birdiness=d['birdiness'], species=d['species'], **L))
print(f'days with complete lead-up weather: {len(rows)}')
FEATS = ['rain_prev3_in', 'rain_then_clear', 'offshore_switch', 'south_prev2', 'pressure_3d_hpa', 'warmup_f', 'calm_prev3']

report = {}
for sea in ('fall', 'spring'):
    R = [r for r in rows if r['season'] == sea]
    cut = sorted(r['birdiness'] for r in R)[int(len(R) * 0.9)]
    top, rest = [r for r in R if r['birdiness'] >= cut], [r for r in R if r['birdiness'] < cut]
    def stat(rs, k):
        v = [r[k] for r in rs if r[k] is not None]
        if not v: return None
        return round(sum(v) / len(v), 2) if k in ('rain_then_clear', 'offshore_switch', 'south_prev2') else round(median(v), 2)
    report[sea] = {k: (stat(top, k), stat(rest, k)) for k in FEATS}
    print(f'\n{sea.upper()} top 10% (n={len(top)}) vs rest (n={len(rest)})  [share for yes/no features, median otherwise]')
    for k in FEATS:
        print(f'  {k:18s} top {report[sea][k][0]}   rest {report[sea][k][1]}')

# Does adding lead-up features improve the forecast model? (same unicorn target and 5-fold CV as fit_model.py)
with contextlib.redirect_stdout(io.StringIO()):
    fm = runpy.run_path(str(ROOT / 'fit_model.py'), run_name='leadup')
by_date = {r['date']: r for r in rows}
idx = [i for i, ds in enumerate(fm['keep']) if ds in by_date and all(by_date[ds][k] is not None for k in FEATS)]
X0, y = fm['X'][idx], fm['y'][idx]
LX = np.array([[by_date[fm['keep'][i]][k] for k in FEATS] for i in idx])

def cv(X, seeds=(1, 2, 3, 4, 5)):
    Z = np.c_[np.ones(len(X)), (X - X.mean(0)) / X.std(0)]
    lls, hits = [], []
    for seed in seeds:
        rng = np.random.default_rng(seed); order = rng.permutation(len(y)); p = np.zeros(len(y))
        for te in np.array_split(order, 5):
            tr = np.setdiff1d(order, te); w = fm['fit'](Z[tr], y[tr]); p[te] = 1 / (1 + np.exp(-Z[te] @ w))
        lls.append(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        hits.append(y[np.argsort(-p)[:len(y) // 20]].mean())
    return float(np.mean(lls)), float(np.mean(hits))

base = cv(X0)
print(f'\nModel check on {len(y)} days ({int(y.sum())} unicorns), 5-fold CV averaged over 5 shuffles:')
print(f'  current model          log-loss {base[0]:.4f}  top-5% hit rate {base[1]:.2f}')
results = {'current': base}
for j, k in enumerate(FEATS):
    r = cv(np.c_[X0, LX[:, j]]); results[k] = r
    print(f'  + {k:20s} log-loss {r[0]:.4f}  hit {r[1]:.2f}  ({"better" if r[0] < base[0] - 0.0005 else "no gain"})')
allr = cv(np.c_[X0, LX]); results['all_leadup'] = allr
print(f'  + all lead-up features  log-loss {allr[0]:.4f}  hit {allr[1]:.2f}')
(ROOT / 'outputs' / 'leadup.json').write_text(json.dumps(dict(season_compare=report, model=results, n=len(y)), indent=1))

# Best pair, and which way each one pushes (sign of its coefficient in a full fit)
pair = [FEATS.index('rain_prev3_in'), FEATS.index('warmup_f')]
pr = cv(np.c_[X0, LX[:, pair]]); results['rain_prev3+warmup'] = pr
print(f'  + rain_prev3 + warmup   log-loss {pr[0]:.4f}  hit {pr[1]:.2f}')
Xp = np.c_[X0, LX[:, pair]]
Z = np.c_[np.ones(len(Xp)), (Xp - Xp.mean(0)) / Xp.std(0)]
w = fm['fit'](Z, y)
print(f'  coefficients: rain_prev3 {w[-2]:+.2f}, warmup {w[-1]:+.2f}')
import csv
with (ROOT / 'outputs' / 'leadup_days.csv').open('w', newline='') as f:
    wr = csv.DictWriter(f, fieldnames=['date'] + FEATS); wr.writeheader()
    for r in rows: wr.writerow({k: r[k] for k in ['date'] + FEATS})
(ROOT / 'outputs' / 'leadup.json').write_text(json.dumps(dict(season_compare=report, model=results, n=len(y)), indent=1))
