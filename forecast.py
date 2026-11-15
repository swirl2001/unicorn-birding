"""Unicorn Birding Day forecast for Battery Godfrey (Presidio, SF).

Scores today + 6 days with model.json (from fit_model.py): chance that the day is a "unicorn",
a top-5% day for species variety at a normal level of birding effort (2016-2025 eBird history).
Weather, matched to what the model was trained on:
  - night wind (8 pm-6 am): NWS gridpoint over the Presidio (MTR/83,106), Open-Meteo at Fort Point as backup
  - 24 h pressure change, overnight rain: Open-Meteo at Fort Point
  - high temperature: Open-Meteo at Fort Point, 6 am-6 pm (the history used the Fort Point station; no SFO data)
Writes site/data.json and state.json; emails sign-ups once per date when a day within 48 h is a strong bet.
Standard library only. Run: python3 forecast.py
"""
import json, math, os, smtplib, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
PT = ZoneInfo('America/Los_Angeles')
UA = {'User-Agent': '(unicorn-birding alert, personal project)'}
MODEL = json.loads((ROOT / 'model.json').read_text())

ALERT_CHANCE = 0.25   # email when a day within 48 h reaches this (about 5x the everyday odds)
NWS_GRID = 'https://api.weather.gov/gridpoints/MTR/83,106'
OM = 'https://api.open-meteo.com/v1/forecast?timezone=America%2FLos_Angeles&past_days=2&forecast_days=8'
FORT_POINT = OM + ('&latitude=37.8106&longitude=-122.4655&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,precipitation,precipitation_probability,visibility&daily=sunrise'
                   '&wind_speed_unit=mph&precipitation_unit=inch&temperature_unit=fahrenheit')
SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
WORDS = dict(N='north', NE='northeast', E='east', SE='southeast', S='south', SW='southwest', W='west', NW='northwest')


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def sector(deg):
    return None if deg is None else SECTORS[int(((deg + 22.5) % 360) // 45)]


def season_terms(d):
    a = d.timetuple().tm_yday / 365.25 * 2 * math.pi
    return [g(k * a) for k in (1, 2, 3) for g in (math.sin, math.cos)]


def iso_hours(dur):
    days = int(dur.split('P')[1].split('D')[0]) if 'D' in dur else 0
    t = dur.split('T')[1] if 'T' in dur else ''
    return days * 24 + (int(t.split('H')[0]) if 'H' in t else 0)


def nws_hourly(props, key, conv):
    """Expand an NWS gridpoint layer into {local naive hour: value}."""
    out = {}
    for v in props.get(key, {}).get('values', []):
        if v['value'] is None:
            continue
        start, dur = v['validTime'].split('/')
        t = datetime.fromisoformat(start).astimezone(PT).replace(tzinfo=None)
        for h in range(iso_hours(dur)):
            out[t + timedelta(hours=h)] = conv(v['value'])
    return out


def weather():
    fp_all = get(FORT_POINT)
    fp = fp_all['hourly']
    hours = [datetime.fromisoformat(t) for t in fp['time']]
    om = {k: dict(zip(hours, fp[k])) for k in ('wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'pressure_msl',
                                               'precipitation', 'precipitation_probability', 'visibility')}
    om['sunrise'] = {date.fromisoformat(t[:10]): datetime.fromisoformat(t) for t in fp_all['daily']['sunrise']}
    tmax = {}
    for t, v in zip(hours, fp['temperature_2m']):
        if v is not None and 6 <= t.hour < 18:
            tmax[t.date()] = max(v, tmax.get(t.date(), -999))
    try:
        props = get(NWS_GRID)['properties']
        nws_spd = nws_hourly(props, 'windSpeed', lambda x: x * 0.621371)
        nws_dir = nws_hourly(props, 'windDirection', float)
        om['nws_gust'] = nws_hourly(props, 'windGust', lambda x: x * 0.621371)
        om['nws_pop'] = nws_hourly(props, 'probabilityOfPrecipitation', float)
    except Exception as e:  # NWS is often flaky; Open-Meteo covers it
        print('NWS unavailable:', e, file=sys.stderr)
        nws_spd, nws_dir = {}, {}
    return om, tmax, nws_spd, nws_dir


def night_wind(d, om, nws_spd, nws_dir):
    """Mean speed and vector-mean direction, 8 pm the evening before to 6 am."""
    start = datetime(d.year, d.month, d.day) - timedelta(hours=4)
    spd, u, v, src = [], 0.0, 0.0, set()
    for h in range(10):
        t = start + timedelta(hours=h)
        if t in nws_spd and t in nws_dir:
            s, deg = nws_spd[t], nws_dir[t]; src.add('NWS')
        elif om['wind_speed_10m'].get(t) is not None:
            s, deg = om['wind_speed_10m'][t], om['wind_direction_10m'][t]; src.add('Open-Meteo')
        else:
            continue
        spd.append(s); u += s * math.sin(math.radians(deg)); v += s * math.cos(math.radians(deg))
    if not spd:
        return None, None, None
    deg = None if math.hypot(u, v) / len(spd) < 0.5 else math.degrees(math.atan2(u, v)) % 360
    return sum(spd) / len(spd), deg, '+'.join(sorted(src))


def morning_mean(series, d):
    vals = [series.get(datetime(d.year, d.month, d.day, h)) for h in range(6, 11)]
    vals = [x for x in vals if x is not None]
    return sum(vals) / len(vals) if vals else None


def chance(d, night_dir, night_mph, dp, t, rain):
    m = d.month; fall, spring = m in (8, 9, 10, 11), m in (3, 4, 5)
    x = season_terms(d) + [1.0 if fall and night_dir in MODEL['offshore'] else 0.0,
                           1.0 if spring and night_dir in ('S', 'SE', 'SW') else 0.0,
                           night_mph, dp, t, 1.0 if rain else 0.0]
    # cap each input at 2.5 SD of the training data so a freak forecast can't extrapolate the model
    z = MODEL['coef'][0] + sum(c * max(-2.5, min(2.5, (xi - mu) / sd))
                               for c, xi, mu, sd in zip(MODEL['coef'][1:], x, MODEL['mean'], MODEL['sd']))
    return 1 / (1 + math.exp(-z)), x


def describe(d, night_dir, night_mph, dp, t, rain):
    good, bad = [], []
    m = d.month
    if m in (9, 10):
        good.append('peak fall migration')
    elif m in (8, 11) or m in (4, 5):
        good.append('migration season')
    else:
        bad.append('off-season')
    if night_dir and m in (8, 9, 10, 11) and night_dir in MODEL['offshore']:
        good.append(f'{WORDS[night_dir]} wind overnight')
    if night_dir and m in (3, 4, 5) and night_dir in ('S', 'SE', 'SW'):
        good.append(f'{WORDS[night_dir]} wind overnight')
    if t is not None and t >= 72:
        good.append(f'warm ({round(t)}°F)')
    if dp is not None and dp >= 1.5:
        good.append('pressure rising')
    if rain:
        bad.append('rain overnight')
    if night_mph is not None and night_mph >= 15:
        bad.append(f'windy overnight ({round(night_mph)} mph)')
    return good, bad


def morning_conditions(d, om, nws_spd):
    """Birding hours (6-11 am): mean wind and peak gust in mph; rain chance from 8 pm the night before to 11 am."""
    def pick(nws, om_key, t):
        v = nws.get(t)
        return v if v is not None else om[om_key].get(t)
    hours = [datetime(d.year, d.month, d.day, h) for h in range(6, 11)]
    wind = [x for x in (pick(nws_spd, 'wind_speed_10m', t) for t in hours) if x is not None]
    gust = [x for x in (pick(om.get('nws_gust', {}), 'wind_gusts_10m', t) for t in hours) if x is not None]
    start = datetime(d.year, d.month, d.day) - timedelta(hours=4)
    pop = [x for x in (pick(om.get('nws_pop', {}), 'precipitation_probability', start + timedelta(hours=h)) for h in range(15))
           if x is not None]
    vis = [om['visibility'].get(t) for t in hours]
    vis = [v for v in vis if v is not None]
    return (round(sum(wind) / len(wind)) if wind else None, round(max(gust)) if gust else None,
            round(max(pop)) if pop else None, round(min(vis) / 1609.34, 1) if vis else None)


def build(now=None):
    now = now or datetime.now(PT)
    om, tmax, nws_spd, nws_dir = weather()
    days = []
    for i in range(7):
        d = (now + timedelta(days=i)).date()
        mph, deg, src = night_wind(d, om, nws_spd, nws_dir)
        nd = sector(deg) if mph is not None else None
        p_now, p_prev = morning_mean(om['pressure_msl'], d), morning_mean(om['pressure_msl'], d - timedelta(days=1))
        dp = p_now - p_prev if p_now is not None and p_prev is not None else None
        start = datetime(d.year, d.month, d.day) - timedelta(hours=4)
        rain_in = sum(om['precipitation'].get(start + timedelta(hours=h)) or 0 for h in range(10))
        t = tmax.get(d)
        m_wind, m_gust, rain_pct, vis_mi = morning_conditions(d, om, nws_spd)
        sunrise = om['sunrise'].get(d)
        if None in (mph, dp, t):
            p, note = 0.0, 'No forecast yet'
            good, bad = [], []
        else:
            p, _ = chance(d, nd, mph, dp, t, rain_in > 0.01)
            good, bad = describe(d, nd, mph, dp, t, rain_in > 0.01)
            note = ', '.join((good + bad if p >= MODEL['base_rate'] else bad + good)[:2]).capitalize()
        label = 'today' if i == 0 else 'tomorrow' if i == 1 else d.strftime('%A')
        summary = (f"{', '.join(good).capitalize() or 'Nothing special lining up'}"
                   f"{'; but ' + ', '.join(bad) if bad else ''}.")
        days.append(dict(
            dow=d.strftime('%a'), date=d.strftime('%b %-d'), iso=d.isoformat(), label=label, chance=round(p, 4),
            note=note, summary=summary, within_48h=i <= 1,
            night_wind_mph=None if mph is None else round(mph, 1), night_wind_from=nd, night_wind_deg=None if nd is None else round(deg), wind_source=src,
            pressure_change_hpa=None if dp is None else round(dp, 1), max_temp_f=None if t is None else round(t),
            rain_overnight_in=round(rain_in, 2), morning_wind_mph=m_wind, morning_gust_mph=m_gust, rain_pct=rain_pct,
            morning_vis_mi=vis_mi, sunrise=sunrise.strftime('%-I:%M') if sunrise else None))
    return dict(
        generated=now.astimezone(timezone.utc).isoformat(timespec='minutes'),
        generated_local=now.strftime('%a %b %-d, %-I:%M %p'),
        base_rate=MODEL['base_rate'], cut_species=MODEL['cut_species'],
        method=(f"A unicorn day is one of the top 5% of days at Battery Godfrey for variety: about {MODEL['cut_species']}+ species "
                "for a normal group of birders. We learned what those days have in common from 10 years of eBird checklists "
                f"({MODEL['fitted_days']} birded days, 2016–2025), adjusted for how many people were out. Time of year matters most "
                "(late September and October lead), then warm, dry weather with wind off the land overnight. Even a perfect "
                "setup is only about a 1-in-4 shot, because who shows up and luck matter too. Weather is from the National "
                "Weather Service over the Presidio and Open-Meteo at Fort Point; no SFO data."),
        days=days)


def send_emails(subject, body):
    user, password = os.environ.get('GMAIL_USER'), os.environ.get('GMAIL_APP_PASSWORD')
    recipients = [e.strip() for e in os.environ.get('ALERT_EMAILS', '').split(',') if e.strip()]
    if not (user and password and recipients):
        print('[dry run, no Gmail settings] would email:', subject, '|', body)
        return False
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, f'Unicorn Birding Day <{user}>', user
    msg['Bcc'] = ', '.join(recipients)
    msg.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    print(f'emailed {len(recipients)} address(es)')
    return True


def main():
    data = build()
    (ROOT / 'site' / 'data.json').write_text(json.dumps(data, indent=1))
    state_path = ROOT / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'alerted': []}
    page = os.environ.get('PAGE_URL', '')
    for d in data['days']:
        if d['within_48h'] and d['chance'] >= ALERT_CHANCE and d['iso'] not in state['alerted']:
            subject = f"Drop everything and go birding {d['label']}! Unicorn day at Battery Godfrey"
            body = (f"Skip work. Grab your binoculars. Battery Godfrey looks like a unicorn day {d['label']}.\n\n"
                    f"{d['summary']}\n\n"
                    f"Chance of a top-5% variety day: {round(d['chance'] * 100)}% "
                    f"(about {round(d['chance'] / MODEL['base_rate'])}x a normal day). Get there early: "
                    f"the big movement is in the first couple of hours after sunrise.\n\n"
                    f"{page}\n\nReply 'stop' to unsubscribe.")
            if send_emails(subject, body) or os.environ.get('MARK_DRY_RUN'):
                state['alerted'].append(d['iso'])
    state['alerted'] = sorted(set(state['alerted']))[-50:]
    state_path.write_text(json.dumps(state, indent=1))
    for d in data['days']:
        print(f"{d['label']:<10} {d['chance'] * 100:5.1f}%  night {d['night_wind_from']} {d['night_wind_mph']} mph ({d['wind_source']}), "
              f"dP {d['pressure_change_hpa']} hPa, high {d['max_temp_f']}F, rain {d['rain_overnight_in']} in | {d['note']}")


if __name__ == '__main__':
    main()
