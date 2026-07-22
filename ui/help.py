"""In-app Help / User Guide (opens as a pop-up dialog).

Single source of truth for the how-to. Keep this in step with the
features; the PDF in docs/ mirrors it.
"""

import streamlit as st

GUIDE_MD = """
### 🌾 AgriRadius Pro — how to use it

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
- Pick the **Year** for the satellite analysis.
- *Example:* `10.6588, 77.0089` (Pollachi), radius 10 km.

#### 4. The map (sidebar → Layers)
- Tick a layer to turn it on — it computes live the first time
  (10–30 s), then loads instantly.
- **Overlay opacity** makes layers see-through.
- **Compute quality** (Light / Balanced / Heavy): Heavy = sharpest but
  heaviest — drop to **Light** if it's slow or Earth Engine is busy.
- If tiles look missing after zooming, click **Refresh map**.

Layers include: Dynamic World land cover, Cropland Confidence, Paddy,
Maize, Plantations (coconut/arecanut), Banana, Aquaculture ponds,
Soil pH / Organic Carbon / Nitrogen.

#### 5. The results tabs (below the map)
Some tabs fetch data only when you click a button, so nothing loads
unless you ask.
- **Summary** — land-cover mix, cropland confidence & 3-year stability.
- **Villages** — per-village cropland & ranking; the trained crop
  classifier (incl. the coconut model).
- **Charts** — visual breakdown.
- **Crop Cycle** — sowing→peak→harvest pattern; paddy & plantation
  checks.
- **Rainfall** — 10-year history.
- **Forecast** — **Live conditions now** (rain, temperature, humidity,
  wind, sun/solar, UV, soil moisture & temp, evapotranspiration, and a
  **drying-suitability score**) with an *Auto 5m* refresh toggle, plus
  the 16-day outlook & dry-window.
- **Soil** — pH, organic carbon, nitrogen, texture.
- **Allied Sectors** — livestock & poultry, estimated **dairy pool** &
  **feed demand**, aquaculture, sericulture, fisheries, fertiliser,
  horticulture.
- **Mandi** — today's prices, the **MSP floor** comparison, a multi-year
  **price trend**, and a **variety/grade** breakdown.
- **Ground Truth** — log what a field grows (trains the app for your
  area) + soil cards, **and a 📤 Upload Field Data tab** to bulk-upload
  a CSV/Excel of points (latitude, longitude, crop; village/acreage/
  notes optional). Download the template, fill it, upload — the points
  are saved to the shared dataset for calibration and the classifier.
- **Downloads** — build a full **PDF / Excel report** of everything.

#### 6. How much to trust it
Open the **Data & Confidence** box at the top of the results.
**Measured** things (rainfall, crop vigour, radar detection, prices) are
reliable; **modelled/classified** things (land-cover class, soil at
250 m) are best read as **ranges**. Rule of thumb: *trust the direction
and the ranges; verify the edges on the ground.* It improves as your
team logs ground truth.

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
- *Tiles missing after zoom?* Click **Refresh map**.
- *Map jumped?* Re-search your location.
"""


@st.dialog("How to use AgriRadius Pro", width="large")
def _show_guide():
    st.markdown(GUIDE_MD)


def help_button():
    """A sidebar button that opens the guide as a pop-up."""
    if st.button("❔ How to use this app", use_container_width=True,
                 key="help_btn"):
        _show_guide()
