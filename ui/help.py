"""In-app Help / User Guide (opens as a pop-up dialog).

Single source of truth for the how-to. Keep this in step with the
features; the PDF in docs/ mirrors it.
"""

import streamlit as st

GUIDE_MD = """
### 🌾 Ground Intel — how to use it

Turn any place in South India into a complete farming report from free
satellite and government data — crops, soil, rainfall, live weather,
market prices and livestock/allied sectors.

---

#### 1. Opening
- Use **Google Chrome** (desktop or phone). No installation.
- If asked, type the **password** you were given.
- **First load can take ~30 s** if the app was asleep — then it's fast.

#### 2. The screen
- **Left sidebar** = all your controls (Search, Input, Layers, Compute
  quality, Service health).
- **Main area** = the map on top, and **Analysis Results** tabs below.
- On a phone the sidebar folds into the ☰ menu (top-left).

#### 3. Choose what to analyse (sidebar → Input)
- **Analysis Mode:** *Area (radius)* studies a circle; *Point location*
  studies one exact spot.
- **Input Method:** type coordinates, or pick **Map Click** and click
  the map. You can also paste a **Google Maps link** or place name in
  the Search box at the top.
- **Radius (km):** slider or exact value — keep it **7–10 km** (big
  circles are slow and use more compute).
- Pick the **Year** for the satellite analysis. The **current year**
  uses a rolling 12-month window so detectors still work mid-season;
  a completed past year is the safest reference.
- New here? Click **✨ Try a sample area (Pollachi)** in the sidebar to
  load a demo location instantly.
- *Example:* `10.6588, 77.0089` (Pollachi), radius 10 km.

#### 4. The map (sidebar → Layers)
- Tick a layer to turn it on — it computes live the first time
  (10–30 s), then loads instantly.
- **Overlay opacity** makes layers see-through.
- **Compute quality** (Light / Balanced / Heavy): Heavy = sharpest but
  heaviest — drop to **Light** if it's slow or Earth Engine is busy.
- If tiles look missing after zooming, click **Refresh map**.
- **Compare layers (grid):** above the map, switch *Map view* to
  *Compare layers (grid)* to see every ticked layer in its own panel
  side by side. Toggle **synced zoom** (all panels follow the top-left
  *master* — pan/zoom it and the rest match) or make them independent,
  set **max panels** (up to all your ticked layers), and use
  **⛶ Full screen**. **Double-click any panel** to expand it full and
  double-click again to restore. Each panel shows its key figure on a
  translucent badge; use the **Overlay opacity** slider to make sparse
  detection layers easier to see.

**The layers, grouped as they appear in the sidebar:**

*Crops & land cover (satellite):* Dynamic World land cover, Cropland
Confidence, Paddy (radar), Plantations (coconut/arecanut), Banana,
Maize / kharif, WorldCereal cropland, Aquaculture ponds.

*Measured ground records (not satellite estimates):*
- **SHC measured soil-test** — Soil Health Card lab results. Switch
  *SHC resolution* to **Village detail** to get each village's own
  samples; hover any village for its full nutrient readout, sample
  count and the cycle the samples come from.
- **Coconut — govt crop survey** — every coconut plot logged against
  its survey number in the Karnataka Crop Survey (2023-24), aggregated
  to 3,318 villages across Hassan, Mandya, Tumakuru, Ramanagara,
  Chitradurga and Mysuru. Paint it by intensity, acres, plot count or
  grower count.
- **Irrigation source by district** — how the land is watered (canal /
  tank / borewell / dug well), from Land Use Statistics 2022-23. Seven
  views via *Irrigation metric*, including **dominant source** and
  **gross:net** cropping intensity.
- **Canal command areas (India-WRIS)** — the land a canal actually
  serves ("ayakat").

*Irrigation from satellite (💧 Irrigation group):*
- **Irrigation confidence (0-5)** — start here. Colours land by **how
  many independent methods agree** it is irrigated. 3+ means go look.
- **Irrigated cropland — summer green** — cropland still green and
  moist through **February-May**. Nothing survives a Karnataka summer
  without applied water.
- **Irrigation events — radar** — Sentinel-1 wetting events. The only
  layer that **sees through cloud**, so it is the one to trust on the
  coast and in Malnad.
- **Canal/tank-fed vs borewell-fed** — irrigated land far from any
  permanent surface water is almost certainly borewell-fed.
- **Multi-crop land**, **LGRIP30 irrigated vs rain-fed**, **WorldCereal
  irrigation** — three independent second opinions.

*Soil (modelled):* Soil pH / Organic Carbon / Nitrogen (SoilGrids,
250 m).

#### 5. The results tabs (below the map)
Some tabs fetch data only when you click a button, so nothing loads
unless you ask.
- **Summary** — land-cover mix, cropland confidence & 3-year stability.
- **Villages** — per-village cropland & ranking; the trained crop
  classifier (incl. the coconut model).
- **Charts** — visual breakdown.
- **Crop Cycle** — sowing→peak→harvest pattern; paddy & plantation
  checks.
- **💧 Irrigation** — the full irrigation stack for this area (see 5c).
  The government source split loads straight away; the two heavy parts
  (**village-by-village** and **satellite measurement**) each wait for
  a button, so opening the tab never starts an Earth Engine job.
- **🌳 Forest vs Farmland** — separates natural forest from tree crops
  using JRC GFC2020 (which excludes agricultural plantations by
  definition), so plantation area can be reported **net of forest**.
  It also cross-checks detected area against the department's own
  district crop figures. Matters most in Malnad, Kodagu, Shivamogga,
  Chikkamagaluru and the coastal belt.
- **Rainfall** — 10-year history.
- **Forecast** — **Live conditions now** (rain, temperature, humidity,
  wind, sun/solar, UV, soil moisture & temp, evapotranspiration, and a
  **drying-suitability score**) with an *Auto 5m* refresh toggle, plus
  the 16-day outlook & dry-window.
- **Soil** — pH, organic carbon, nitrogen, texture, plus a
  **Land Capability** panel (SLUSI detailed soil survey): how much of
  the district's *surveyed* land is prime/arable (Class I-IV) vs
  non-arable (V-VIII), with links to the official survey PDFs. It's
  authoritative but **historical reference** (surveys 1960-2018,
  surveyed watersheds only) — not current land use.
- **Allied Sectors** — livestock & poultry, estimated **dairy pool** &
  **feed demand**, aquaculture, sericulture, fisheries, fertiliser,
  horticulture.
- **Mandi** — today's prices, the **MSP floor** comparison, a multi-year
  **price trend**, and a **variety/grade** breakdown.
- **Ground Truth** — log what a field grows (trains the app) + soil
  cards. The **📤 Upload Field Data** tab lets you collect points two
  ways: **📍 on-site on your phone** (tap *Get my location*, pick the
  crop — or *Not sure* to skip — and Save, one tap per field), or
  **📄 upload a CSV/Excel** of many points at once (lat, lon, crop;
  village/acreage/notes optional; template provided). Everything saves
  to the shared dataset for calibration and the classifier.
- **Downloads** — build a full **PDF / Excel report**. It carries
  *everything the app holds for the circle you selected*: every map
  layer as an image, land cover, villages, crop cycle, the full
  irrigation stack (district split, village table, satellite figures,
  and which methods ran), forest vs farmland, the coconut survey and
  its accuracy scoring, department crop cross-checks, Minor Irrigation
  Census, rainfall, forecast, soil incl. SHC and land capability,
  allied sectors, mandi prices with MSP and history, and your ground
  truth. Anything that could not be computed is written as **n/a with
  the reason**, never silently dropped — so the report never looks
  more complete than it is. Excel gets the same content as sheets.

#### 5b. Panels that appear under the map
These show up on their own when the data covers where you are looking,
and stay quiet when it doesn't:
- **🥥 Measured coconut — government crop survey** — what the survey
  actually recorded here: acres, plots, growers, villages, irrigation
  share, and every village ranked. Run *Plantation Detection* first and
  it also **scores the satellite against the survey** for the same
  circle — the app's strongest accuracy check.
Irrigation and Forest vs Farmland used to sit here; both are now full
**tabs** in Analysis Results, so nothing is duplicated under the map.

#### 5c. The Irrigation tab, and what its numbers mean
Open **💧 Irrigation** in Analysis Results. Top to bottom:
- **District source split** (loads immediately) — borewell / canal /
  tank / well from Land Use Statistics 2022-23, with a chart, a
  district table and a plain instruction on **how to target field
  staff here**.
- **🏘️ Irrigation village by village** — press *Measure irrigation for
  every village here* and each village's irrigated area is measured
  from its own polygon, the same resolution as the SHC village layer.
  Village level is as fine as public data goes: survey-number
  irrigation exists only in the Bhoomi RTC/Pahani and the seasonal
  Crop Survey, neither of which has an open bulk API.
- **🚰 Canal command areas** — press *Harvest* once and the server
  fetches them from India-WRIS (needs open internet and an Indian IP,
  so a browser can't; the server also tries on every restart).
- **🛰️ What the satellite sees** — press *Measure irrigated area here
  (satellite)*. Takes ~40-60 s; **wait for the spinner to finish, and
  don't click twice** — a second click while it is working is ignored.
  You get cropland area, summer-green irrigated area, **2+ and 3+
  method agreement**, radar events, the borewell-vs-canal split, the
  black-cotton-soil warning, and the accuracy band **for your zone**.

**Read the "(N/5 ran)" label on the agreement figure.** The five
methods are summer greenness, radar events, multi-cropping, LGRIP30
and WorldCereal. If a method cannot run the panel now says so and
names it, and if the agreement figures cannot be computed at all they
read **n/a — never 0**. A zero means "measured, and it is zero"; n/a
means "not measured". They used to look identical, which made a
missing number read as a real one.

- **Quote the agreement figure, not one product.** "2+ methods agree"
  is defensible; a single layer is an estimate.
- **Borewell vs canal decides your method.** Karnataka is 56.6%
  borewell-irrigated, and borewells appear on no canal map. In
  Raichur (77% canal) work from command areas; in Tumakuru (99.5%
  borewell) don't bother — use the satellite layers.
- **Accuracy is not uniform.** 80-90% in the semi-arid interior and
  north; **60-75% on the coast and in Malnad**, where rain keeps
  everything green. The panel names your zone and its band.
- **Rabi green ≠ irrigated in north Karnataka.** Rabi jowar and
  chickpea on black cotton soil live on stored soil moisture. That's
  why these layers use **February-May**, when nothing survives without
  applied water.

#### 6. How much to trust it
Open the **Data & Confidence** box at the top of the results — it now
separates four tiers:
1. **Measured on the ground** — Soil Health Card lab results, the
   coconut crop survey, irrigation-by-source statistics, mandi prices,
   your own ground truth. Not estimates.
2. **Direct satellite measurement** — crop vigour, rainfall, radar
   detection and radar irrigation events.
3. **Modelled / classified — read as ranges** — land-cover class, soil
   at 250 m, satellite irrigation, LGRIP30, WorldCereal.
4. **Cross-checks** — independent datasets compared, satellite scored
   against the surveys, and irrigation scored 0-5 by method agreement.

It also spells out the **two traps** the app avoids (rain-fed rabi on
black cotton soil, and borewells that appear on no canal map) and the
**honest limit**: nobody — government or commercial — has a reliable,
current, plot-level irrigated/rain-fed flag for all of Karnataka.

Rule of thumb: *trust the direction and the ranges; verify the edges on
the ground.* It improves as your team logs ground truth.

**Know how current each number is.** Every tab shows a small dated
caption (🟢 live · 🟡 periodic release · 🟠 modelled · ⚪ historical
reference), and the **Data & Confidence** box lists an *"as of"* date
for every source. Live weather and mandi prices are today's; the
coconut crop survey is 2023-24; irrigation-by-source is 2022-23; the
livestock census is 2019; soil (SoilGrids) is a 2020 modelled baseline;
LGRIP30 over India is 2015; the SLUSI land-capability survey is
1960-2018. Always read the date so you don't mistake older reference
data for today's ground reality.

#### 7. Please test mindfully 🙏
This is a **free, open-source** setup (Google Earth Engine) with a
**limited shared monthly compute budget**:
- one heavy layer at a time; keep the radius reasonable;
- avoid rapid repeated clicks — let a layer finish;
- use **Light** compute quality if slow.
The sidebar **Service health** panel shows the live EECU compute meter
(how much is left; it resets on the 1st of each month).

#### Quick fixes
- *Slow first open?* It was asleep — wait ~30 s.
- *"Earth Engine is busy"?* Wait a minute, click Refresh, or use Light.
- *A layer looks missing / nothing painted?* Click **Refresh map** — it
  rebuilds every overlay with a fresh Earth Engine token. (Tokens
  expire; the app now checks each one before drawing and renews it
  automatically, and if a layer truly can't be drawn it says so on the
  map instead of showing plain satellite. The sidebar **Service
  health** panel has a *Map tiles* line: checked / renewed / failed.)
- *Irrigation or coconut panel not showing?* Those cover Karnataka
  only — the coconut survey covers six districts. Outside their
  coverage they stay hidden rather than showing blanks.
- *Map jumped?* Re-search your location.
"""


@st.dialog("How to use Ground Intel", width="large")
def _show_guide():
    st.markdown(GUIDE_MD)


def help_button():
    """A sidebar button that opens the guide as a pop-up."""
    if st.button("❔ How to use this app", use_container_width=True,
                 key="help_btn"):
        _show_guide()
