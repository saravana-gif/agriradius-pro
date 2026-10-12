# Spices and plantation crops (turmeric, chilli, tender coconut): what OneRoot Ground Intel should do
*Panel input from a spices and plantation-crop scientist (ICAR-IISR, TNAU Bhavanisagar/Erode, UAS Dharwad/Raichur, CPCRI). Maize and banana are left to colleagues.*

## 1. Crop calendars and weather-driven risks

**Turmeric** (Erode, Gobi, Bhavani, Salem; Chamarajanagar, Mysuru; Belagavi in the Gokak/Raibag area)
- **Season:** planted May–Jun with green-leaf mulch. Canopy closes Aug–Oct. Leaves senesce in Jan. Harvest runs Jan–Mar, then 10–15 days of boiling and sun-drying through Feb–Apr.
- **Rhizome rot (Pythium), Jun–Sep.** Driven by temperatures above 30 °C plus saturated or waterlogged soil, and spread by irrigation water ([Vikaspedia](https://en.vikaspedia.in/agriculture/crop-production/integrated-pest-managment/ipm-for-spice-crops/ipm-strategies-for-turmeric/diseases-and-symptoms)).
  - Alert when heavy rain is forecast over several days and Tmax is ≥30 °C. Advice: clear the drains, hold irrigation, drench at the first collar rot.
- **Leaf blotch (Taphrina), Oct–Nov.** Favoured by 21–23 °C with 80% RH ([TNAU Agritech](https://agritech.tnau.ac.in/govt_schemes_services/aas/turmeric_ex.html); [Springer](https://link.springer.com/article/10.1007/BF02050748)).
- **Leaf spot (Colletotrichum), Aug–Dec, in humid spells.** Shoot borer is active Jul–Oct.
- **The most neglected loss is rain during curing (Feb–Apr).** It spoils colour and leaves the crop with mould.

**Chilli** – three different systems:
- **Byadgi** (Haveri, Dharwad, Gadag): rainfed on black soils. Transplanted Jul–Aug, flowers Oct–Nov, picked 6–10 times between Nov and Jan/Feb ([NIFTEM](https://niftem.ac.in/newsite/pmfme/wp-content/uploads/2022/08/byadgichilliprocessing.pdf)). Rainfed yield is 0.5–1.25 t/ha against 3.75–5 t/ha irrigated.
- **Ballari/Raichur:** irrigated from the Tungabhadra canal. Transplanted Aug–Sep, harvested Dec–Apr.
- **Ramanathapuram/Virudhunagar mundu:** depends on the northeast monsoon. Sown Sep–Oct, harvested Jan–Apr.

Pests and diseases (the published thresholds disagree, so treat these as starting points to tune):
- **Black thrips (*Thrips parvispinus*):** outbreak across AP, Telangana and Karnataka in 2021–22, with 90–95% of flowers damaged in NBAIR surveys ([NBAIR](https://www.nbair.res.in/sites/default/files/2023-04/ICAR-NBAIR%20report%20thrips.pdf)).
  - At Raichur, counts peaked in standard weeks 47–50 (late Nov to mid Dec) and were negatively correlated with rain ([Plant Archives](https://www.plantarchives.org/article/278_WEATHER-RELATED-INTRA-PLANT-DISTRIBUTION-OF-INVASIVE-CHILLI-THRIPS-_THRIPS-PARVISPINUS-KARNY_.pdf)).
  - Trigger: the dry, warm spell that follows Oct–Nov rains during flowering means "scout the flowers now". Tap flowers onto white paper to count.
- **Common thrips (*S. dorsalis*) and yellow mite:** a field study quotes ETLs of 2 thrips per leaf and 1 mite per cm² ([IJAgS](https://epubs.icar.org.in/index.php/IJAgS/article/download/121815/48077/336431)).
- **Leaf curl virus:** carried by whitefly, thrips and mites. Highest risk is a warm, dry spell in the first 60 days after transplanting. Advice: raise nurseries under insect net, use yellow sticky traps, rogue infected plants.
- **Anthracnose / fruit rot:** 28–32 °C with RH of 92–95% or more and rain at red-ripe stage ([BAMIS](https://www.bamis.gov.bd/res/public/calendars/2023/03/19/26628.pdf)). A cyclone in Nov–Dec is the worst case.
- **Powdery mildew:** about 25 °C, around 85% RH, dry days with humid nights, Dec–Feb.
- **Drying (Dec–Mar):** rain on chilli drying in the field causes discolouration and aflatoxin. Byadgi is priced on colour.

## 2. Can turmeric and chilli be detected from free satellite data? Partly.

**Published work is thin.**
- I found no peer-reviewed Sentinel crop-type map of turmeric in India.
- The closest is a turmeric *yield* model for the Lower Bhavani basin (BPNN, R² 0.96, driven by NDVI, MSI and rainfall) ([Global NEST 2025](https://journal.gnest.org/publication/gnest_07463)).
- For chilli there is Omdena's unsupervised Sentinel-2 work in Guntur and Bellary, which publishes no accuracy figure ([Omdena](https://www.omdena.com/projects/ai-for-chilli-crop-detection)).
- Mixed Indian smallholder Sentinel-2 maps reach 70–84% overall accuracy ([ICRISAT](https://oar.icrisat.org/11558/1/07_Crop%20type%20identification%20with%20focus%20on%20field%20level%20information.pdf)).

**Signatures that separate them:**
- **Turmeric:** mulched, bare-looking ridges in Jun–Jul (low NDVI, rough radar). NDVI peaks late, around Oct–Dec (~0.7+), and senesces sharply in Jan–Feb. That is a 9-month curve.
  - Maize peaks Jul–Sep. Banana and sugarcane stay green through the summer.
  - The real confusers are **cassava (tapioca) in Salem/Namakkal/Erode**, ginger, and young sugarcane.
- **Chilli:** a low, open canopy (NDVI peaks only around 0.5–0.65) with Oct–Dec peaks.
  - It looks almost exactly like **cotton**, which grows on the same calendar in Haveri/Dharwad/Raichur, and like onion and groundnut.
  - Expect 60–75% per-class accuracy for chilli; Erode turmeric can probably reach 80% or more.

**Why the current classifier cannot do this:**
- `gee/classifier.py` lumps Turmeric into "LongDuration" and Chilli into "Seasonal".
- It trains on **village centroids** (`labelled_points`), which cannot work for 0.2–1 ha plots.
- `gee/features.py` uses annual aggregates (percentiles and medians), which throw away *when* the peak happens. Monthly features for NDVI/NDRE and VH (Jun, Aug, Oct, Dec, Feb) are needed.

**Ground truth needed:**
- About 80–150 GPS field points per target class per agro-region, taken ≥20 m inside fields across ≥20 villages, plus a similar number for each confuser (cassava, sugarcane, cotton, onion, maize, banana).
- That comes to 600–900 points per region, roughly 20 person-days of roadside survey. Repeat the next season.
- `MIN_POINTS = 20` is far too low.
- **Shortcut for Karnataka:** the app already ingests the FRUITS/Bhoomi crop survey for coconut. The same survey records turmeric and chilli at survey-number level. Filter for quality, use it as training labels, and validate with your own field points.

## 3. Tender coconut is not copra

- **Harvest rhythm:** each farm is harvested every 30–45 days all year. Nuts reach tender stage about 6.5 months after fertilisation and full maturity at 12 months ([Mongabay/CPCRI Hebbar](https://india.mongabay.com/2024/07/high-temperatures-lead-to-decline-in-coconut-production-spiked-prices/amp/)).
- **Stress lag:** heat or water stress at button stage causes shedding, which shows up as fewer tender nuts **about 4–6 months later**. Stress during primordium and ovary development hits yields for 1–3 years ([Sri Lanka dry-spell work](https://dl-cri.nsf.gov.lk/items/0056eb55-a889-4ee5-864a-e069deffc3ea)).
  - So a hot April predicts a supply dip in Sep–Nov. That lead time comes from biology, not from a weather forecast.
- **Demand:** peaks Mar–May. In May 2026, retail in Yadgir reached ₹70–80 a nut against ₹30–40 normally ([report](https://cropgpt.ai/heatwave-sends-tender-coconut-prices-soaring-in-yadgir)).
- **Pests:** eriophyid mite and rugose whitefly worsen in hot, dry months. Mite scarring lowers the grade of tender nuts.

**What the app should forecast:**
- **(a)** Pickable nuts per catchment for the next 4–8 weeks, from a harvest roster per farm.
- **(b)** A lagged supply outlook for months +1 to +3 (or +4 to +6), as normal / below / well below, from past stress months computed from CHIRPS, Tmax and ET0.
- **(c)** Heat-stress alerts: Tmax ≥37 °C on the 16-day forecast triggers ET0-scaled irrigation advice, husk and frond basin mulching, and holding back over-harvesting.
- **(d)** A seasonal price index for Maddur, Malavalli, K.R. Pet and Srirangapatna.
- Remove the copra drying score from the tender-coconut view.

## 4. Advice when the rains fail

| Crop | How failed rain hurts | What to advise |
|---|---|---|
| Turmeric (irrigated) | Through groundwater and reservoirs: Bhavanisagar/LBP storage in May, and northeast-monsoon recharge | Decide at planting (May–Jun): low storage plus a poor pre-monsoon means cut the area, use drip and mulch, don't buy seed rhizome on credit |
| Byadgi chilli (rainfed) | Delayed onset; a dry spell of 3 weeks or more at flowering (Oct–Nov) drops flowers | Use the CRIDA district contingency plan ([Haveri](https://krishi.icar.gov.in/jspui/handle/123456789/30700)): delay transplanting or switch to a short crop; give protective irrigation from farm ponds at flowering; mulch. Sourcing: expect thin Jan–Mar arrivals and buy from irrigated Ballari |
| Mundu chilli (TN) | Northeast monsoon failure, but cyclone waterlogging is just as bad | Advise on stand establishment and drainage |
| Tender coconut | Lagged 4–6 months, effects last years | Mulch basins and bury husks; give water to bearing palms first; shift sourcing to canal-command areas (KRS/Cauvery, PAP-Pollachi) |

Free monitoring sources for this: [CWC weekly reservoir bulletin](https://rsms.cwc.gov.in/admin/storage/bulletins/bulletin-19-02-2026-82.pdf) (issued Thursdays; covers KRS, Kabini, Bhavanisagar, Tungabhadra).

## 5. Free data sources (checked 12 Oct 2026)

- **AGMARKNET via data.gov.in** (free API key, daily; the app already uses it):
  - Turmeric (Erode) and Dry Chillies are reported.
  - **Tender Coconut is reported by Maddur, Malavalli, K.R. Pet and Srirangapatna** ([via acrop](https://acrop.app/prices/tendercoconut/karnataka/mandya)), but it is **missing from `COMMODITIES` in `core/mandi.py`**.
  - Its "₹25,000/quintal" can only mean per 1,000 nuts (₹25 a nut). Verify this.
  - I could not query the API live because the network was blocked from this machine.
- **Spices Board** ([daily](https://www.indianspices.com/marketing/price/domestic/daily-price.html), [weekly](https://www.indianspices.com/marketing/price/domestic/weekly-price.html)): **cardamom only**, no turmeric or chilli. Not useful.
- **Erode Regulated Market:** auctions run daily, but there is no public feed. Use AGMARKNET for Erode, or have staff log the rates.
- **NCDEX turmeric futures** (TMCFGRNZM; Nizamabad basis, Erode as an additional delivery centre) ([guide](https://www.sahi.com/blogs/turmeric-futures-trading-ncdex-complete-guide)): delayed quotes are free on ncdex.com. This is the only free forward price, and the app should show it as "market expectation", not as advice.
- **Coconut Development Board:** has district production statistics only, **no tender coconut price feed** ([Statistics](https://www.coconutboard.gov.in/Statistics.aspx)).
- **Krishi Marata Vahini** (Karnataka's state price portal): exists, but I could not verify a URL or feed.
- **Agromet advisories:**
  - IMD GKMS district bulletins, Tuesdays and Fridays, free ([IMD Agrimet](https://imdagrimet.gov.in/cropAdvisory_3.php)).
  - TNAU agromet bulletins ([example](https://agritech.tnau.ac.in/agrometeorologicaladvisory/pdf/tnau_acrc/2024/apr/English%20Bulletin%20on%2002.04.2024%20Virudhunagar.pdf)).
  - IISR's advisories are aimed at Kerala, so use the TNAU and UAS crop-protection pages instead.

## 6. Ranked improvements

| # | What | Data | Dev-days | User | Decision it changes |
|---|---|---|---|---|---|
| 1 | Curing and drying-risk alerts for turmeric (Feb–Apr) and chilli (Dec–Mar), reusing the copra drying score | Open-Meteo | 1–2 | Both | When to dig, boil or pick; cover the crop; sourcing expects quality discounts |
| 2 | Add Tender Coconut to the mandi list; seasonal price index for Erode, Byadgi and Maddur; NCDEX turmeric curve | AGMARKNET archive, NCDEX | 2–3 | Sourcing | Timing of buying and holding |
| 3 | Rule engine linking crop stage and weather to pests and diseases (rhizome rot, leaf blotch, black thrips, anthracnose, leaf curl), output as Kannada/Tamil WhatsApp share text | Open-Meteo hourly RH/T/rain, district calendars, sowing date entered by staff | 4–6 | Ground staff | Scouting and spray timing, drainage |
| 4 | Tender coconut heat-stress alert with ET0-based irrigation and mulch advice | Open-Meteo Tmax, ET0, VPD | 2–3 | Ground staff | Irrigation in Mar–May; flags the future dip |
| 5 | Tender coconut supply forecast: farm harvest roster in Sheets plus the lagged stress index | Sheets, CHIRPS, ERA5/Open-Meteo archive | 5–7 | Sourcing | Which catchments to buy from, and how much, over the next 1–3 months |
| 6 | Rain-failure early warning: rainfall vs normal, dry-spell tracker, reservoir storage, CRIDA contingency triggers | CHIRPS, CWC, CRIDA PDFs | 5–8 | Both | Planting area for turmeric, Byadgi transplant or switch, protective irrigation |
| 7 | Turmeric and chilli mapping: split the classes, add monthly features, train on field points and Bhoomi labels | GEE, crop survey, a field campaign | 10–15, plus about 20 field-days per region | Sourcing | Village acreage and volume for turmeric and chilli |

Do 1–6 before 7: they cost about two weeks combined and work without new maps. Turmeric mapping in Erode is feasible. Separating chilli from cotton will stay mediocre.

## Questions for the OneRoot owner

1. **Tender coconut:** do you source from Tall palms (Maddur style) or from dwarf/hybrid orchards? Do your staff already record each farm's harvest date and nut count? The supply forecast depends on that.
2. **Chilli:** which belt matters most (rainfed Byadgi, irrigated Ballari/Raichur, or Tamil Nadu mundu), and are you buying dry or green chilli?
3. **Turmeric and chilli mapping:** will you commit about 20 field-days per region this season to collect 600+ GPS-labelled fields, including cassava, cotton and sugarcane? Without that, mapping should not start.

---
*Note to caller: a failed local test call to the data.gov.in API printed the project's API key in my tool output on this machine. The connection was refused, so the key was not transmitted anywhere. No action needed beyond awareness.*