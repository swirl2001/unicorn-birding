# Unicorn Birding Day

A web page and email alert for the rare day Battery Godfrey (Presidio, San Francisco)
lights up with the most bird species. Live at https://swirl2001.github.io/unicorn-birding/

**Unicorn day** = a top-5% day for species variety at a normal level of birding effort
(about 77+ species for 3 checklists), from 10 years of eBird history (2016–2025, 944 birded days).

What the history says: time of year matters most (late September–October, then April–May).
On top of that, big days are warmer and dry, with wind off the land overnight in fall
(south winds in spring) and a rising barometer. Cross-validated, the model's top-scored days
were unicorns 17% of the time versus 5% for a random birded day; its chances are well calibrated
but rarely exceed ~30%, because who's out and luck matter a lot.

- `pull_ebird.py` downloads daily checklists and species for eBird hotspot L999240 (needs `EBIRD_API_KEY`).
- `analyze.py` adds Golden Gate weather (Fort Point, Pier 17, SF Bar buoy, SFO) and compares the best days.
- `fit_model.py` fits the logistic model and writes `model.json`.
- `forecast.py` scores the next 7 days (NWS gridpoint over the Presidio, Open-Meteo at Fort Point and SFO),
  writes `site/data.json`, and emails sign-ups once per date when a day within 48 h reaches 25%.
- `.github/workflows/check.yml` runs it at ~5:40 am and pm Pacific and publishes the page.
  Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_EMAILS` (comma-separated, sent as BCC).

Data: eBird, Cornell Lab of Ornithology; NOAA National Weather Service, NDBC, CO-OPS and Iowa Environmental Mesonet; Open-Meteo.
