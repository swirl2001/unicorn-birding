"""Build site/examples.json: three record checklists from Battery Godfrey with species, counts and weather.

Uses data/examples/ (checklist views + taxonomy from the eBird API), data/raw/ (to judge how rare
each species is at the site) and outputs/daily_birds_weather.csv (Golden Gate weather).
Run: python3 examples.py
"""
import csv, json, math, re, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
EX = ROOT / 'data' / 'examples'
SECTORS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']

EXAMPLES = [
    dict(sub='S173104816', kind='Biggest checklist in 10 years', season='spring'),
    dict(sub='S75452945', kind='Best fall day', season='fall'),
    dict(sub='S106491033', kind='Best spring day (besides May 9, 2024)', season='spring'),
    dict(sub='S402902254', kind='Fall 2026', season='fall', group='recent'),
    dict(sub='S405157915', kind='Fall 2026', season='fall', group='recent'),
    dict(sub='S317091626', kind='Best spring 2026 checklist', season='spring', group='recent'),
]

# Hand-written takeaways, from the checklist notes and the weather record
INSIGHTS = {
    'S402902254': [
        'Clear, with a 5–10 mph northeast breeze off the land from midnight until it flipped onshore at 12:50 pm. Temperatures climbed from the 60s to near 80.',
        'A Sandhill Crane flew over on a heads-up from another birder, one of very few ever seen in San Francisco.',
        'An immature Cocos Booby, a tropical seabird, foraged in the channel and was photographed.',
        'Waterfowl and shorebirds on the move: Greater Scaup flocks with a Canvasback and a Gadwall, plus Marbled Godwits and Dunlin.',
    ],
    'S405157915': [
        'Light northeast winds, clear skies and temperatures in the 60s: another offshore-wind morning.',
        'A strong songbird flight, mostly thrushes and pipits, until about 9:30 am.',
        'A big flicker flight, with 20 moving together at once, including Yellow-shafted and intergrade birds.',
        'Huge totals: 2,565 Band-tailed Pigeons in flocks of hundreds, 1,645 Brown Pelicans, and a raptor push from 11:30 am.',
    ],
    'S317091626': [
        'An "offshore wind event": a steady 5–10 mph east-northeast wind all morning, sun and highs in the upper 70s.',
        'Whimbrels and Long-billed Curlews flew out the Gate early, while 400 Elegant Terns fed in the channel.',
        "An early Vaux's Swift in active northbound migration, and five Wilson's Snipe confirmed from photos.",
        '16 birders on the battery. Activity was steady all day, though slower than hoped for such good conditions.',
    ],
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


ARCHIVE = ('https://archive-api.open-meteo.com/v1/archive?timezone=America%2FLos_Angeles&wind_speed_unit=mph'
           '&precipitation_unit=inch&temperature_unit=fahrenheit')


def archive_weather(ds):
    """Modeled weather (Open-Meteo archive) for dates after the station history: same fields as the CSV."""
    d = date.fromisoformat(ds); d0 = datetime(d.year, d.month, d.day)
    rng = f'&start_date={d - timedelta(days=1)}&end_date={d}'
    fp = json.loads(urllib.request.urlopen(ARCHIVE + rng + '&latitude=37.8106&longitude=-122.4655'
                    '&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,precipitation', timeout=60).read())['hourly']
    sfo = json.loads(urllib.request.urlopen(ARCHIVE + rng + '&latitude=37.6189&longitude=-122.3750&daily=temperature_2m_max',
                     timeout=60).read())['daily']
    H = {datetime.fromisoformat(t): i for i, t in enumerate(fp['time'])}
    def rows(a, b):
        return [H[t] for t in (a + timedelta(hours=h) for h in range(int((b - a).total_seconds() // 3600))) if t in H]
    def vec(idx):
        u = sum(fp['wind_speed_10m'][i] * math.sin(math.radians(fp['wind_direction_10m'][i])) for i in idx)
        v = sum(fp['wind_speed_10m'][i] * math.cos(math.radians(fp['wind_direction_10m'][i])) for i in idx)
        return math.degrees(math.atan2(u, v)) % 360, sum(fp['wind_speed_10m'][i] for i in idx) / len(idx)
    night, morn = rows(d0 - timedelta(hours=4), d0 + timedelta(hours=6)), rows(d0 + timedelta(hours=6), d0 + timedelta(hours=11))
    prev = rows(d0 - timedelta(hours=18), d0 - timedelta(hours=13))
    nd, ns = vec(night); md, ms = vec(morn)
    pm = lambda idx: sum(fp['pressure_msl'][i] for i in idx) / len(idx)
    return dict(night_wind_dir=nd, night_wind_mph=ns, morning_wind_dir=md, morning_wind_mph=ms,
                morning_gust_mph=max(fp['wind_gusts_10m'][i] for i in morn), pressure_change_hpa=pm(morn) - pm(prev),
                max_temp_f=sfo['temperature_2m_max'][-1], rain_night_in=sum(fp['precipitation'][i] or 0 for i in night),
                morning_vis_mi=None, source='Open-Meteo archive (modeled)')


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
        w = wx.get(date) or archive_weather(date)
        lists_that_day = next(len(d['lists']) for d in raw if d['date'] == date)
        out.append(dict(
            kind=ex['kind'], season=ex['season'], group=ex.get('group', 'records'), wx_source=w.get('source', 'Golden Gate stations'), date=date, sub=ex['sub'], url=f"https://ebird.org/checklist/{ex['sub']}",
            observer=c.get('userDisplayName'), observers=c.get('numObservers'), hours=round(num(c.get('durationHrs')) or 0, 1),
            start=c['obsDt'][11:16], lists_that_day=lists_that_day, species_count=len(sp),
            weather=dict(
                night_wind_deg=None if not compass(num(w['night_wind_dir'])) else round(num(w['night_wind_dir'])),
                night_wind_mph=round(num(w['night_wind_mph'])),
                morning_wind_deg=round(num(w['morning_wind_dir'])), morning_wind_mph=round(num(w['morning_wind_mph'])),
                morning_gust_mph=round(num(w['morning_gust_mph'])),
                night_wind=f"{compass(num(w['night_wind_dir'])) or 'calm'} {round(num(w['night_wind_mph']))} mph",
                morning_wind=f"{compass(num(w['morning_wind_dir']))} {round(num(w['morning_wind_mph']))} mph, gusts {round(num(w['morning_gust_mph']))}",
                high_f=round(num(w['max_temp_f'])), pressure_change_hpa=round(num(w['pressure_change_hpa']), 1),
                rain=(num(w['rain_night_in']) or 0) > 0.01,
                fog=(None if num(w['morning_vis_mi']) is None else num(w['morning_vis_mi']) < 1)),
            top=[dict(name=s['name'], count=s['count']) for s in top],
            rare=[dict(name=s['name'], days=days_seen.get(s['name'], 0)) for s in rare][:6],
            insights=INSIGHTS[ex['sub']], birded_days=len(birded),
            species=[dict(name=s['name'], count=(s['count'] if not s['x'] or s['count'] else None)) for s in sp]))
        print(ex['sub'], date, len(sp), 'species;', 'top', [(s['name'], s['count']) for s in top])
    (ROOT / 'site' / 'examples.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
