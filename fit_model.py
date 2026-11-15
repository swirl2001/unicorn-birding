"""Fit the Unicorn Birding Day model from outputs/daily_birds_weather.csv (run analyze.py first).

Unicorn day = species count, adjusted to a standard effort of 3 checklists by 3 observers,
in the top 5% of all days 2016-2025. A logistic model gives P(unicorn) from the time of year
plus weather a forecast can provide. Writes model.json for forecast.py.
"""
import csv, json, math
from datetime import date
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent
rows = list(csv.DictReader((ROOT / 'outputs' / 'daily_birds_weather.csv').open()))

def f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def season_terms(ds):
    a = date.fromisoformat(ds).timetuple().tm_yday / 365.25 * 2 * math.pi
    return [g(k * a) for k in (1, 2, 3) for g in (math.sin, math.cos)]

# Effort adjustment (same model as analyze.py)
E = np.array([[1, math.log1p(int(r['lists'])), math.log1p(int(r['observers']))] + season_terms(r['date']) for r in rows])
sp = np.array([float(r['species']) for r in rows])
b = np.linalg.lstsq(E, sp, rcond=None)[0]
std = sp - b[1] * (np.log1p([int(r['lists']) for r in rows]) - math.log1p(3)) \
         - b[2] * (np.log1p([int(r['observers']) for r in rows]) - math.log1p(3))
cut = float(np.quantile(std, 0.95))
y_all = (std >= cut).astype(float)

OFFSHORE = ('N', 'NE', 'E')
def sector(deg):
    if deg is None: return None
    return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][int(((deg + 22.5) % 360) // 45)]
WEATHER = ['offshore_night_fall', 'south_night_spring', 'night_wind_mph', 'pressure_change_hpa', 'max_temp_f', 'rain_night']
def weather_terms(ds, night_dir, night_mph, dp, tmax, rain):
    m = int(ds[5:7]); fall, spring = m in (8, 9, 10, 11), m in (3, 4, 5)
    return [1.0 if fall and night_dir in OFFSHORE else 0.0,
            1.0 if spring and night_dir in ('S', 'SE', 'SW') else 0.0,
            night_mph, dp, tmax, 1.0 if rain else 0.0]

X, y, keep = [], [], []
for r, yy in zip(rows, y_all):
    w = weather_terms(r['date'], sector(f(r['night_wind_dir'])), f(r['night_wind_mph']), f(r['pressure_change_hpa']),
                      f(r['max_temp_f']), (f(r['rain_night_in']) or 0) > 0.01)
    if None in w: continue
    X.append(season_terms(r['date']) + w); y.append(yy)
X, y = np.array(X), np.array(y)
mu, sd = X.mean(0), X.std(0)
Z = np.c_[np.ones(len(X)), (X - mu) / sd]

def fit(Z, y, lam=1.0):
    w = np.zeros(Z.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-Z @ w)); W = p * (1 - p)
        H = Z.T @ (Z * W[:, None]) + lam * np.diag([0] + [1] * (Z.shape[1] - 1))
        g = Z.T @ (p - y) + lam * np.r_[0, w[1:]]
        w -= np.linalg.solve(H, g)
    return w

def cv(cols):
    rng = np.random.default_rng(1); idx = rng.permutation(len(y)); p = np.zeros(len(y))
    for te in np.array_split(idx, 5):
        tr = np.setdiff1d(idx, te); w = fit(Z[tr][:, cols], y[tr]); p[te] = 1 / (1 + np.exp(-Z[te][:, cols] @ w))
    ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    order = np.argsort(-p); top = order[:len(y) // 20]
    return ll, y[top].mean(), p

base = -np.mean(y * np.log(y.mean()) + (1 - y) * np.log(1 - y.mean()))
season_cols = list(range(7)); all_cols = list(range(Z.shape[1]))
ll_s, hit_s, _ = cv(season_cols); ll_w, hit_w, p_cv = cv(all_cols)
print(f'days {len(y)}, unicorn cut {cut:.0f} species at standard effort, base rate {y.mean():.3f}')
print(f'log-loss  no info {base:.4f} | season {ll_s:.4f} | season+weather {ll_w:.4f}')
print(f'hit rate of top-5% scored days  season {hit_s:.2f} | season+weather {hit_w:.2f}')
print('calibration (cv): ', [(round(lo, 2), round(float(p_cv[(p_cv >= lo) & (p_cv < hi)].mean()), 3), round(float(y[(p_cv >= lo) & (p_cv < hi)].mean()), 3), int(((p_cv >= lo) & (p_cv < hi)).sum()))
                              for lo, hi in ((0, .02), (.02, .05), (.05, .1), (.1, .2), (.2, 1)) if ((p_cv >= lo) & (p_cv < hi)).any()])
w = fit(Z, y)
names = ['intercept'] + [f'season{i}' for i in range(6)] + WEATHER
for n, c in zip(names, w): print(f'  {n:22s} {c:+.2f}')
(ROOT / 'model.json').write_text(json.dumps(dict(
    cut_species=round(cut), base_rate=float(y.mean()), mean=mu.tolist(), sd=sd.tolist(), coef=w.tolist(), names=names,
    weather=WEATHER, offshore=list(OFFSHORE), fitted_days=len(y)), indent=1))
