# Karnataka Irrigation Data — Sources, APIs and a Field-Targeting Build

Prepared 17 August 2026 for OneRoot.
**Goal:** find farmland in Karnataka that is *irrigated* (canal / tank / borewell / dug well / lift) rather than rain-fed, as precisely as possible, so field staff can target it.

---

## The short version

There is exactly **one** government dataset that records irrigation source against an individual survey number: the **RTC / Pahani** (Bhoomi), Column 8 plus the Khushki / Tari / Bagayat extent split. It is authoritative for land *class* but stale for present-day borewells, because it is a revenue-settlement field.

The only **per-plot dataset refreshed every season** is the **Karnataka Crop Survey (Bele Sameekshe)**, which geo-tags every survey number each season and records the type of irrigation adopted. Neither has an open bulk API.

Everything else is either an aggregate (district / taluk / village) or a satellite estimate. **No product — government or commercial — gives you a reliable, current, plot-level irrigated/rain-fed flag for all of Karnataka today.** Anyone claiming otherwise is selling a satellite estimate.

So the practical build is:

> **KGIS parcel geometry + KGIS lat-long→survey-number API + a Sentinel-2 February–May greenness classifier, calibrated on RTC / Crop Survey labels, with India-WRIS canal command areas as a hard prior.**

---

## What's in this bundle

| File | What it is |
|---|---|
| `Karnataka_Irrigation_Data_Sources.xlsx` | The main deliverable. 8 sheets: plot-level sources, aggregate statistics, satellite layers, live APIs, real district data, the targeting playbook, commercial vendors, and the access-request letters worth writing. |
| `data/ka_net_irrigated_area_by_source_2022_23_wide.csv` | Real data: net irrigated area by source, all 31 Karnataka districts, 2022-23. |
| `data/ka_net_gross_irrigated_area_by_source_2022_23_long.csv` | Same, long format, net + gross, 372 records. |
| `scripts/01_pull_irrigation_stats.py` | Bulk pullers for the two APIs that actually work (district-level LUS, village-level Minor Irrigation Census). |
| `scripts/02_wris_command_areas.py` | Harvests India-WRIS canal command areas and canal networks as GeoJSON. |
| `scripts/03_kgis_latlong_to_survey.py` | The lat/long ↔ survey number bridge via the KGIS Web API. Ready to run once KSRSAC provisions you. |
| `scripts/04_gee_karnataka_irrigation.js` | The full Earth Engine irrigation classifier, with the Karnataka-specific traps handled. |

---

## The one number that should shape your strategy

Karnataka's net irrigated area in 2022-23 was **5.04 million hectares**, and **56.6% of it is borewell/tubewell**:

| Source | Net irrigated area (ha) | Share |
|---|---:|---:|
| Borewell / Tubewell | 2,848,789 | 56.6% |
| Canal (Government) | 1,058,749 | 21.0% |
| Other Source (mostly lift) | 630,468 | 12.5% |
| Open / Dug Well | 395,672 | 7.9% |
| Tank | 103,852 | 2.1% |

*(Source: Land Use Statistics, DES-Agri, Ministry of Agriculture & Farmers Welfare. Pulled live 17 Aug 2026.)*

**Why this matters:** borewells are invisible to canal command-area maps, and they are drilled far faster than land records get updated. So for well over half of Karnataka's irrigated land, the only ways to find it are satellite imagery and current land records — not infrastructure maps.

The split flips completely by district, and that should drive how you deploy field staff:

**Canal districts — use India-WRIS command-area polygons, no satellite work needed:**
Raichur (77% canal), Yadgir (52%), Mandya (47%), Koppal (29%), Davanagere (28%).

**Borewell districts — command-area maps are useless, you need satellite or land records:**
Tumakuru (99.5% borewell), Chitradurga (99.3%), Vijayapura (91.4%), Haveri (89.9%), Koppal (66%), Bagalkote (64%).

---

## The three things to do this week

1. **Email `kgissupport@ksrsac.in`** asking for K-GIS Web API base URLs and keys, specifically services 1 (Admin Hierarchy, with the `type=bhoomi` cross-walk), 3 (Survey Number), 7 (Geometric Polygon Area → WKT) and 11 (Nearby Location Details → lat/long to survey number). This is the smallest ask on the list and the biggest unlock: it is what turns a field-staff GPS ping into a survey number, and a survey number into a polygon you can score.

2. **Test `https://kodi.karnataka.gov.in/Crop_Survey/api/CropSurvey/Getdata?key=MjgyMjExODE=` from an Indian IP.** It is registered on data.gov.in under the Karnataka Agriculture Department and appears to be the only open, machine-readable, government-hosted crop-survey JSON endpoint in existence. I could not read its payload from outside India. If it returns plot-level rows with an irrigation field, it changes your whole plan.

3. **Email ICRISAT's geospatial group in Hyderabad** for the asset ID and licence of their India Irrigated/Rainfed Cropland **10 m, 2024-25** map. ICRISAT's own announcement claims "around 90% accuracy in mapping cropland" and "nearly 70% accuracy in distinguishing irrigated from rainfed systems." It is the newest and most relevant satellite product that exists for your problem, it is India-specific, and right now it is only visible through a fragile-looking Earth Engine app (`ee-my-pytest`) with no published asset ID, no licence and no DOI. Lead scientist is **Dr Muralikrishna Gumma**, Principal Scientist – Geospatial and Big Data Sciences; media contact `parkavi.kumar@icrisat.org`. Costs nothing to ask.

---

## Four corrections to claims you will otherwise hit

These are widely repeated and wrong; each would cost you weeks.

1. **GFSAD30 South Asia does not contain irrigated/rain-fed classes.** NASA's metadata confirms a single band with three classes over range 0–2: cropland, non-cropland, water. The product in that family that *does* split irrigated from rain-fed is **LGRIP30**. (Check the exact numeric code order against the user guide before hardcoding a mask — an inverted mask fails silently.)

2. **LGRIP30's headline 91.2% accuracy is CONUS-only**, and applies to V002 — which covers only the continental United States. **No Indian accuracy figure has ever been published for LGRIP30.** V001 (2015) is the version that covers India. Also note class 0 is ocean *and inland water bodies*, so Karnataka's tanks and reservoirs fall in it.

3. **ESA WorldCereal's irrigation product has no published accuracy metrics at all.** Its own ESSD paper says outright that limited ground information gave them "little means to run a quantitative validation of irrigation products as such," so they ran only a qualitative assessment. It is deliberately conservative, trained on sparse data biased toward centre-pivot systems, and under-maps Asia. It is not the safe 10 m default it looks like — use it as a lower bound.

4. **Sentinel-1 revisit is 6 days again, not 12.** Most write-ups still say 12 days because Sentinel-1B failed in December 2021. But S1C launched 5 December 2024 (operational May 2025) and S1D launched 4 November 2025 (operational from mid-April 2026), restoring the two-satellite six-day exact repeat cycle. That is the difference between being able to detect individual irrigation events and only being able to classify seasons. Do still check the acquisition-plan KMLs for your Karnataka tiles — constellation capability and actual tasking are not the same thing.

---

## The Karnataka-specific trap nobody documents

**Rabi jowar, chickpea and safflower on black cotton soil (vertisols) in Vijayapura, Bagalkot, Kalaburagi, Bidar and Vijayanagara is largely RAIN-FED** — sown in September–October into wet vertisols and matured entirely on stored soil moisture, with no irrigation at all.

A naive "green in rabi ⇒ irrigated" rule will systematically mislabel a large fraction of north Karnataka's rain-fed rabi area as irrigated. This is very likely a major reason the coarse global products (Ambika 250 m, IWMI 10 km) over-estimate Indian irrigated area.

**The fix:** use the **summer / Zaid window (mid-February to mid-May)** as your primary discriminator, not rabi. Vertisol-stored moisture cannot carry a crop into March–May; irrigation can. Treat rabi greenness as a weak feature and feed soil texture (NBSS&LUP, or the Karnataka LRI parcel-level soil layer) in as a covariate so the model can learn the interaction.

---

## Expected accuracy, honestly

With good local labels, at parcel level:

- **80–90%** in interior and northern semi-arid Karnataka (Chitradurga, Tumakuru, Kolar, Vijayapura, Kalaburagi, Raichur, Ballari, Bagalkote)
- **60–75%** in coastal Karnataka, Malnad and the Western Ghats (Dakshina Kannada, Udupi, Uttara Kannada, Kodagu, Chikkamagaluru, Shivamogga) — where rainfall keeps everything green year-round and the irrigation signal essentially vanishes

Build a **district-stratified model**, not one statewide model. Benchmark against the **Berambadi watershed** (Gundlupet taluk, Chamarajanagar), which has published ground truth and kappa > 0.9 results — if your pipeline can't reproduce that there, it won't work anywhere.

Also note: published South Asia work reports **rain-fed user's accuracy of only 63%**, meaning over a third of pixels labelled rain-fed are actually irrigated. For your use case that error direction hurts recall — you will miss real targets — so tune your threshold accordingly.

---

## Terminology you will meet in the records

| Kannada term | Meaning |
|---|---|
| **Khushki** (ಖುಷ್ಕಿ) / Jirayat | Dry, rain-fed land |
| **Tari** (ತರಿ) | Wet land — typically canal- or tank-irrigated, paddy |
| **Bagayat** (ಬಾಗಾಯ್ತು) | Garden land — well/borewell-irrigated, horticulture/plantation |
| **Neeravari** (ನೀರಾವರಿ) | Irrigation / irrigated |
| **Ayakat** | Area commanded under a given irrigation source |
| **Kharab A / B** | Uncultivable land within a survey number |
| **Bele Sameekshe** (ಬೆಳೆ ಸಮೀಕ್ಷೆ) | Crop Survey |

The RTC extent block splits total area into Khushki / Tari / Bagayat with **separate revenue assessment rates**. Because that split drives revenue, it is audited — which makes it the most reliable irrigation indicator on the document, more so than Column 8 itself.

---

## Verification status

Endpoints marked **VERIFIED** in the workbook were called successfully on 17 August 2026:

- India Data Portal CKAN — Sources of Irrigation (181,500 rows; Karnataka = 9,024) ✅
- data.gov.in — Source Wise Irrigated Area under LUS (48,782 records) ✅
- data.gov.in — 5th Minor Irrigation Census, village-level dugwells (192,790 records) ✅
- India-WRIS ArcGIS REST — 22 services enumerated in `SubInfoSysLCC`, ArcGIS Server 10.81 ✅
- KGIS Web API documentation — all 12 services with parameters and response fields ✅

Several Indian government hosts (`*.karnataka.gov.in`, `*.nrsc.gov.in`, `micensus.gov.in`, `ingres.iith.ac.in`, `samrakshane.karnataka.gov.in`) geo-restrict or block automated requests from outside India. Those are marked UNVERIFIED in the workbook and should be checked from a browser in India — they generally work fine there.

---

## Sources

Primary data: [India Data Portal — Land Use Statistics](https://ckandev.indiadataportal.com/dataset/land-use-statistics) · [data.gov.in APIs](https://api.data.gov.in/) · [India-WRIS ArcGIS REST](https://arc.indiawris.gov.in/server/rest/services/SubInfoSysLCC?f=pjson) · [K-GIS Web API](https://kgis.ksrsac.in/kgis/webapi.aspx)

Land records: [Bhoomi RTC](https://landrecords.karnataka.gov.in/service2/RTC.aspx) · [Karnataka Crop Survey](https://cropsurvey.karnataka.gov.in/) · [Samrakshane PMFBY](https://www.samrakshane.karnataka.gov.in/) · [Dishaank](https://play.google.com/store/apps/details?id=com.ksrsac.sslr) · [FRUITS](https://fruits.karnataka.gov.in/) · [Evaluation of Quality of Land Records — Karnataka (GoI)](https://cdnbbsr.s3waas.gov.in/s3d69116f8b0140cdeb1f99a4d5096ffe4/uploads/2025/07/20250730596089689.pdf)

Statistics: [Census 2011 Village Directory via SHRUG](https://docs.devdatalab.org/SHRUG-Metadata/Population%20Census/Tables/vd11-metadata/) · [Agriculture Census](https://agcensus.da.gov.in/) · [Karnataka DES](https://des.karnataka.gov.in/english) · [CGWB IN-GRES](https://ingres.iith.ac.in/) · [Dynamic Ground Water Resources of Karnataka 2024](https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17482455401275100516file.pdf) · [ICRISAT District Level Database](http://data.icrisat.org/dld/src/irrigation.html)

Satellite: [LGRIP30](https://gee-community-catalog.org/projects/lgrip30/) · [ESA WorldCereal (ESSD paper)](https://essd.copernicus.org/articles/15/5491/2023/) · [ICRISAT 10 m India map](https://pressroom.icrisat.org/icrisat-unveils-high-resolution-irrigated-rainfed-cropland-map-to-strengthen-national-policy-decisions) · [Gumma et al. 2022 South Asia 30 m](https://doi.org/10.1080/15481603.2022.2088651) · [Ambika et al. 2016](https://www.nature.com/articles/sdata2016118) · [GMIE-100](https://essd.copernicus.org/articles/17/855/2025/) · [Irrigation water sources 60 m](https://www.nature.com/articles/s41597-025-05920-x) · [Berambadi irrigation history](https://www.mdpi.com/2072-4292/10/6/893) · [Berambadi seasonal groundwater irrigation](https://www.mdpi.com/2072-4292/13/10/1960) · [Sentinel-1 plot-scale irrigation detection](https://www.mdpi.com/2072-4292/12/9/1456) · [Bhuvan](https://bhuvan.nrsc.gov.in/)
