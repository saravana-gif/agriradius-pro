# Expert Panel Brief — OneRoot Ground Intel (groundintel.oneroot.farm)

## Who owns it
OneRoot (ENP Farms Pvt Ltd), South India. Used by (a) **ground staff / field officers** and (b) **people at the decision-making table** (sourcing, input-store siting, input sales, insurance, allied-sector decisions). Source code: `F:\AgriRadiusPro` (Python/Streamlit). You may read it.

## What the app does TODAY
User picks a point/village/taluk/district + radius (default near 11.92N 76.94E — Chamarajanagar/Mysuru belt, Karnataka; Tamil Nadu also covered). App computes live:
- **Land cover & cropland** (Dynamic World, ESA WorldCover/WorldCereal, 3-yr stability check)
- **Crop detection**: coconut/arecanut, banana, maize, paddy (Sentinel-1 radar + Sentinel-2 red-edge/phenology); Random-Forest classifier trained on OneRoot ground truth
- **Crop cycle**: cropping intensity, sowing→peak→harvest, harvest windows, per-village acreage, sourcing scores, volume bands (acres × yield)
- **Villages tab** ranked shortlist; **Field Parcels** map layer
- **Irrigation**: satellite irrigated-area (5 methods), Minor Irrigation Census, WRIS command areas
- **Forest vs farmland**
- **Rainfall**: CHIRPS 10 yrs monthly history (monsoon share etc.) — HISTORY ONLY
- **Forecast**: Open-Meteo 16-day (rain mm/prob, tmax/tmin, longest dry window), live current weather, drying-suitability score (copra), air quality
- **Soil**: SoilGrids pH/OC/N/texture, Soil Health Card data, soil moisture (surface, Open-Meteo)
- **Allied**: livestock census 2019, dairy pool, feed demand, aquaculture ponds, sericulture, fisheries
- **Mandi**: AGMARKNET (data.gov.in) today's prices, MSP comparison, multi-year trend, variety breakdown
- **Ground Truth** collection (Google Sheets), crop survey panel
- **Watchlist**: saved areas, diff "what moved since last visit"
- **Ask a question**: deterministic lookup over computed figures (not an LLM)
- Reports: PDF/Excel; Kannada/Tamil labels; Google sign-in for @oneroot.farm

## What it does NOT do (observed gaps)
- No **seasonal / monsoon outlook** (nothing beyond 16 days). No rainfall-vs-normal anomaly, no dry-spell tracking during the season, no drought index.
- No **alerts / push** — everything is pull: someone must open the app and run an analysis.
- No **advisory layer** ("given this, do X") — it describes, it doesn't recommend.
- No pest/disease risk, no reservoir/groundwater status, no price forecasting, no crop-stress/NDVI-anomaly-vs-normal alerts.
- Compute is on-demand per click (GEE quota-limited), not pre-computed.

## Constraints
- **ZERO extra spend.** Free/open data and APIs only; existing fixed-cost Linux server (can run cron jobs), Google Earth Engine non-commercial quota (~150 EECU-hours/month — precious), free Google Sheets, GitHub Actions free tier.
- Ground staff are on phones, often poor connectivity; local languages Kannada and Tamil.
- Team is small; one developer.

## The provocation from the field
A farmer said: *"Even after so much technology, no one warned us about this year's failed rains. If someone had warned us we would have chosen different crops or made different decisions."*
Leadership believes the app must become **real-time and predictive** and must **give suggestions to people in need**, not just numbers.

## Your job
Speak as yourself — a practitioner with 25-30+ years in your field in South India (Karnataka / Tamil Nadu). Be concrete and honest, including about what forecasting can and cannot do. Use web search to verify any free data source / API you recommend (name it, give the URL, say what it costs and its update frequency/resolution). Reading the code is optional but welcome if you want to check something.

## OWNER'S ANSWERS (added after Round 1 — these override assumptions above)
1. **OneRoot does BOTH**: ground staff advise farmers directly (what to sow, when, inputs) AND the company uses the app for its own sourcing / input-sales decisions. Warnings must serve both audiences.
2. **Field staff and farmers use WhatsApp** (not Telegram). Note the zero-cost constraint: the WhatsApp Business/Cloud API charges for business-initiated template messages — any WhatsApp design must be verified as free (e.g. app-generated share text/image/voice note that staff forward via wa.me links or groups/Channels, or only user-initiated service windows).
3. **Priority crops: turmeric, maize, banana, chilli, tender coconut.** **Areas: Karnataka and Tamil Nadu.** Note: the app currently detects maize, banana, coconut, paddy, arecanut — it does NOT detect turmeric or chilli, and its coconut logic is copra-oriented (drying), not tender-coconut (harvested every ~30-45 days, heat/water-stress sensitive, summer demand peak).
