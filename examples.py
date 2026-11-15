"""Build site/examples.json: three record checklists from Battery Godfrey with species, counts and weather.

Uses data/examples/ (checklist views + taxonomy from the eBird API), data/raw/ (to judge how rare
each species is at the site) and outputs/daily_birds_weather.csv (Golden Gate weather).
Run: python3 examples.py
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).parent
EX = ROOT / 'data' / 'examples'
SECTORS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']

EXAMPLES = [
    dict(sub='S173104816', kind='Biggest checklist in 10 years', season='spring'),
    dict(sub='S75452945', kind='Best fall day', season='fall'),
    dict(sub='S106491033', kind='Best spring day (besides May 9, 2024)', season='spring'),
]

# Hand-written takeaways, from the checklist notes and the weather record
INSIGHTS = {
    'S173104816': [
        'Perfect "flight conditions": clear skies and a light east/northeast breeze off the land, warming into the 70s by noon.',
        'Mid-May is the peak of spring songbird passage. Lazuli Buntings, Western Kingbirds and Western Tanagers poured through all morning.',
        'Close to 100 songbirds at a time swirled over the toll plaza, reluctant to cross the Gate.',
        'About 20 birders on the battery, and the extra eyes turned up rarities like Bank Swallow and Solitary Sandpiper.',
    ],
    'S75452945': [
        'A strong, dry north-northeast wind (15–20 mph, gusting near 30) and a fast-rising barometer: wind off the land, the classic fall setup at the Gate.',
        'Waterfowl on the move: flocks of Snow Geese and two Ross\'s Geese heading east, plus Redhead, Canvasback and Gadwall rarely seen here.',
        'Late October brings a different mix from spring: ducks, geese, terns and sparrows instead of buntings and tanagers.',
        'Yellow-rumped Warblers pushed through early, Purple Finches kept coming later, and duck flocks peaked around 10 am.',
    ],
    'S106491033': [
        'An unusually hot early-April day (high 89°F at SFO) after a nearly calm, southerly night: ideal for migrants to fly.',
        'A big morning push of Band-tailed Pigeons (855!) in flock after flock, plus a wave of Whimbrels at dawn.',
        'A hawk watch drew more birders as the day went on; Swainson\'s Hawk was one of the prizes.',
        'Early April mixes lingering winter birds (Surf Scoters, Yellow-rumped Warblers) with the first spring arrivals, so variety runs high.',
    ],
}


def base_name(n):
    return re.sub(r'\s*\(.*\)$', '', n)


def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def compass(deg):
    return None if deg is None else SECTORS[int(((deg + 22.5) % 360) // 45)]


def main():
    tax = {t['speciesCode']: t for t in json.loads((EX / 'taxonomy.json').read_text())}
    raw = [json.loads(p.read_text()) for p in sorted((ROOT / 'data' / 'raw').glob('*.json'))]
    birded = [d for d in raw if d['lists']]
    days_seen = {}
    for d in birded:
        for n in {base_name(o['comName']) for o in d['obs']}:
            days_seen[n] = days_seen.get(n, 0) + 1
    wx = {r['date']: r for r in csv.DictReader((ROOT / 'outputs' / 'daily_birds_weather.csv').open())}

    out = []
    for ex in EXAMPLES:
        c = json.loads((EX / f"{ex['sub']}.json").read_text())
        date = c['obsDt'][:10]
        species = {}
        for o in c['obs']:
            t = tax[o['speciesCode']]
            if t['category'] not in ('species', 'issf', 'form') and not t['comName'].startswith('Rock Pigeon'):
                continue  # skip "gull sp.", hybrids and the like; eBird does count feral Rock Pigeons
            name = base_name(t['comName'])
            s = species.setdefault(name, dict(name=name, count=0, x=False, order=t['taxonOrder']))
            n = o.get('howManyStr')
            if n and n.isdigit():
                s['count'] += int(n)
            else:
                s['x'] = True
            s['order'] = min(s['order'], t['taxonOrder'])
        sp = sorted(species.values(), key=lambda s: s['order'])
        top = sorted(sp, key=lambda s: -s['count'])[:3]
        rare = sorted((s for s in sp if days_seen.get(s['name'], 0) <= 0.02 * len(birded)), key=lambda s: days_seen.get(s['name'], 0))
        w = wx[date]
        lists_that_day = next(len(d['lists']) for d in raw if d['date'] == date)
        out.append(dict(
            kind=ex['kind'], season=ex['season'], date=date, sub=ex['sub'], url=f"https://ebird.org/checklist/{ex['sub']}",
            observer=c.get('userDisplayName'), observers=c.get('numObservers'), hours=round(num(c.get('durationHrs')) or 0, 1),
            start=c['obsDt'][11:16], lists_that_day=lists_that_day, species_count=len(sp),
            weather=dict(
                night_wind=f"{compass(num(w['night_wind_dir'])) or 'calm'} {round(num(w['night_wind_mph']))} mph",
                morning_wind=f"{compass(num(w['morning_wind_dir']))} {round(num(w['morning_wind_mph']))} mph, gusts {round(num(w['morning_gust_mph']))}",
                high_f=round(num(w['max_temp_f'])), pressure_change_hpa=round(num(w['pressure_change_hpa']), 1),
                rain=(num(w['rain_night_in']) or 0) > 0.01,
                fog=(num(w['morning_vis_mi']) is not None and num(w['morning_vis_mi']) < 1)),
            top=[dict(name=s['name'], count=s['count']) for s in top],
            rare=[dict(name=s['name'], days=days_seen.get(s['name'], 0)) for s in rare][:6],
            insights=INSIGHTS[ex['sub']], birded_days=len(birded),
            species=[dict(name=s['name'], count=(s['count'] if not s['x'] or s['count'] else None)) for s in sp]))
        print(ex['sub'], date, len(sp), 'species;', 'top', [(s['name'], s['count']) for s in top])
    (ROOT / 'site' / 'examples.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
