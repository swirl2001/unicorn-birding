# Unicorn Birding Day

A web page and email alert for the rare day Battery Godfrey (Presidio, San Francisco)
lights up with the most bird species.

Status: studying 10 years of eBird history to learn which weather brings the biggest days.
The forecast and alerts switch on once that's done.

- `pull_ebird.py` downloads daily checklists and species for eBird hotspot L999240 (needs `EBIRD_API_KEY`).
- `analyze.py` adjusts species counts for birder effort and season, then compares the best days' weather.
- `site/` is the page, published with GitHub Pages.

Data: eBird, Cornell Lab of Ornithology; NOAA National Weather Service, NDBC and Iowa Environmental Mesonet (SFO observations).
