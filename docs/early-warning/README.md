# Early warning: how it runs (Phase 1)

Plain-language guide for the owner and field leads. Developers: the
module docstrings in `jobs/` and `core/` have the details.

## What happens every morning (05:15 IST, automatic)

| Step | What it does | Where the result shows |
|---|---|---|
| Forecast | ECMWF 15-day forecast for every watched village (Open-Meteo if ECMWF is down) | village pages, alerts |
| Rain | Yesterday's rain from IMD's gridded data; season total vs a 1981-2025 normal, dry days, SPI | village pages, portfolio, alerts |
| Field reports | Copies officers' reports from the Sheet tab **FieldReports** | portfolio, alerts, hit rate |
| Alerts | Checks the rules (`rules/rules.toml`) and logs alerts - at most 2 per village per day | **📣 Alerts & share kit** page |
| Publish | Writes one small page per village and the weekly portfolio | links on the Alerts page |
| Mandi | Archives today's market prices | portfolio price column |

At 04:30 IST a separate job fills the 1981-2025 rain normal, a few
minutes a night until complete (about a week the first time). Until it
finishes, "rain vs normal" shows "?" - never a guess.

## Using it in the field

- **📣 Alerts & share kit** (app sidebar): today's alerts, worst
  first. For a signed-off alert: download the card, tap **Share on
  WhatsApp**, record the voice-note script in your own voice, then tap
  **I shared this**.
- **📝 Field report** (app sidebar), on your phone: tap *Use my
  location*, pick what happened (sown, rain, pest, harvest, price heard,
  borewell, feedback on an alert), add a number or a photo if you have
  one, save. 30 seconds. Never type a farmer's name or phone number.
- **Was it right?** - the bottom of the Field report page lists alerts
  from a week ago. Answer Yes / Partly / No. Rules right less than about
  6 times in 10 get changed or retired.
- **Weekly portfolio** - one row per village, worst first. It is
  internal (it shows drafts and mandi prices): do not forward it.
- **Village pages** - open on a basic phone without signing in. They
  show only signed-off advice. Anyone with the link can read it, so
  send a village's link only to that village.

## Signing off advice (agronomist)

Nothing can be shared with farmers until it is signed. Two files:

1. `rules/rules.toml` - when an alert fires (thresholds) and its English
   draft. Read `draft_en`, then fill `approved_by = "Name"` and
   `approved_on = "2026-10-20"` for that rule.
2. `templates/advice.toml` - the Kannada, Tamil and English card text
   and voice script for each rule. **The Kannada and Tamil were drafted
   without a native-speaker agronomist** - have one read every line,
   correct it, and fill `approved_by` / `approved_on` for each language.

On GitHub: open the file, click the pencil icon, edit, "Commit changes".
The server picks it up within 5 minutes. A typo that breaks a rule does
not break the others: that rule is skipped and named in the job log.

## Server step (once, after these changes)

On the Lightsail box:

    sudo bash /home/agri/agriradius-pro/scripts/setup_lightsail.sh

It is safe to re-run. It installs the Kannada/Tamil fonts, sets up the
village-page web addresses in Caddy, and adds the 04:30 rain-normal job.

## Watched villages

Edit the **Villages** tab of the Google Sheet (columns: village_id,
village, district, state, lat, lon, crops, active). Until it has rows,
the system uses 7 example town centres
(`data/reference/watch_villages.example.csv`). Keep each `village_id`
fixed once set: alerts and reports hang off it.

## Data sources and licences

- Rain observed: IMD gridded rainfall 0.25° (via `imdlib`); fallback
  Open-Meteo (non-commercial free tier).
- Rain normal and SPI: CHIRPS v2.0 monthly 1981-2025.
- Forecast: ECMWF open data, CC BY 4.0 - every card credits it.
- Prices: Agmarknet via data.gov.in (prices only, no arrivals).
- No Earth Engine on any of these daily steps.
