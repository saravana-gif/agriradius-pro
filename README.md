# OneRoot AgriRadius Pro

**Agricultural GIS intelligence for South India — turn any location + radius (or a point) into a complete, trustworthy agri report from free satellite and government data.**

Built for OneRoot (ENP Farms Pvt. Ltd.) to power sourcing, input-store siting, input sales, insurance and allied-sector decisions.

---

## What it does

Give it a village, a taluk, a Google Maps link, or exact coordinates, and it returns — computed live, at no data cost:

- **Land cover & cropland confidence** — Dynamic World cross-checked against ESA WorldCover/WorldCereal, with a 3-year stability test.
- **Crop-type detection** — coconut/arecanut, banana, maize, paddy — from radar structure, red-edge indices and phenology; plus a ground-truth-trained Random-Forest classifier that improves as field data accrues.
- **Crop cycle** — cropping intensity, sowing→peak→harvest pulse, per-village acreage and sourcing scores.
- **Soil** — pH, organic carbon, nitrogen, texture (SoilGrids), plus real-time surface soil moisture/temperature.
- **Live weather & drying** — current temperature, humidity, wind, rain, cloud, solar, UV, evapotranspiration + a copra/produce **drying-suitability** score, and a 16-day forecast with dry-window detection.
- **Mandi prices** — today's APMC prices, an **MSP floor** comparison, a multi-year **price trend**, and a **variety/grade** breakdown (AGMARKNET).
- **Allied sectors** — livestock & poultry (2019 Census), derived **dairy pool** & **feed demand**, aquaculture ponds (satellite), sericulture, fisheries, fertiliser and horticulture.

Everything is honest about confidence: direct measurements are flagged separately from modelled/classified layers, and every source is cited on screen.

---

## Real-time / live data sources (all free)

| Source | Used for |
| --- | --- |
| **Google Earth Engine** (Sentinel-1/2, Dynamic World, WorldCover/WorldCereal, SoilGrids, JRC water, SRTM) | Land cover, crop type, soil, water, terrain — computed live |
| **Open-Meteo** | Live conditions (temp, humidity, wind, solar, UV, soil moisture/temp, ET), air quality (PM2.5/PM10), 16-day forecast |
| **data.gov.in (AGMARKNET)** | Mandi prices — current, historical trend, variety-wise |
| **Google Cloud Monitoring** | Real Earth Engine EECU usage meter |
| **Google Sheets** | Shared team ground-truth & soil cards |

Bundled reference data (static): 20th Livestock Census 2019, MSP, sericulture/fisheries/fertiliser/horticulture state figures, Census village boundaries (Karnataka, Tamil Nadu).

---

## Setup

1. **Install dependencies**
   ```
   py -m pip install -r requirements.txt
   ```
2. **Secrets** — create `.streamlit/secrets.toml` (gitignored) with:
   ```toml
   DATA_GOV_API_KEY = "..."          # data.gov.in mandi prices
   GSHEET_ID = "..."                 # shared Google Sheet id (optional)
   GCP_SERVICE_ACCOUNT = '''{ ...service-account JSON... }'''
   ```
   The service account powers Earth Engine, Google Sheets and the EECU meter. It needs: Earth Engine access, `roles/monitoring.viewer` (for the usage meter), and Sheet edit access.
3. **Run**
   ```
   py -m streamlit run app.py
   ```

---

## Earth Engine quota

Non-commercial EE has a monthly EECU-hour budget (Community 150, Contributor 1000). The sidebar **Service health** panel shows a live gauge (used / limit, resets on the 1st) via Cloud Monitoring. Use the **Compute quality** slider (Light / Balanced / Heavy) to trade resolution for compute when needed.

---

## Calibration tools (developer)

Field ground truth lives in `data/ground_truth/`. Run these against Earth Engine to validate/tune detectors:

- `py maize_calib.py [year]` — validate maize gates against the labelled maize fields.
- `py coconut_calib.py [belt] [n]` — validate the coconut detector against the labelled coconut villages.
- `py maize_diag.py` — belt-level NDVI phenology diagnostic.

Import more government data with:
- `py tools/import_livestock.py <file> [State]`
- `py tools/import_sector.py <sericulture|fisheries> <file> [State]`
- `py tools/import_agri.py <fertilizer|horticulture|land_use> <file> [State]`

---

## Deployment

Deploy to **Streamlit Community Cloud** (free) so it runs when your laptop is off; add the same secrets in the app's Secrets settings. From there it can be made installable as a PWA and packaged for the Play Store (TWA).

---

*Trustworthy because it is measured and cross-checked. Powerful because it learns from your fields.*
