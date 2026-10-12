# Agro-meteorologist's view: "No one warned us about the failed rains"

## 1. Was a warning available in 2026? Yes. Clear warnings were issued, early and repeatedly. They did not reach the farmer.

Here is what was issued, in order:

- **13 April 2026.** IMD's first seasonal forecast put the monsoon at **92% of LPA (below normal)**. It was IMD's first below-normal April call in 11 years, and IMD gave El Niño as the reason. ([Outlook Business](https://www.outlookbusiness.com/news/india-monsoon-2026-el-nino-below-normal))
- **29 May 2026.** IMD revised the forecast down to **90% of LPA**. It gave a **60% chance of a "deficient" season and 24% of "below normal"**, so 84% combined. It said Central and South Peninsula would most likely be **below normal (<94% LPA)**, and put the chance of El Niño at 92%. ([Down To Earth](https://www.downtoearth.org.in/amp/story/climate-change/imd-revises-monsoon-forecast-to-90-of-lpa-60-chance-of-deficient-rainfall))
- **NOAA CPC** had an El Niño Advisory in force all season. By September it gave more than 90% odds of a very strong event. ([CPC ENSO discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml))
- **17 June 2026.** ICAR-CRIDA's subdivision table showed **South Interior Karnataka at −31%** and **Tamil Nadu at −37%**. In Karnataka, 15 districts were "deficient" and 3 "large deficient". ([CRIDA 17-Jun table](https://icar-crida.res.in/season_c/Jun_2026/17-Jun-2026.pdf))
- **13 July 2026.** The CRIDA weekly bulletin advised South Interior Karnataka to **postpone kharif sowing because soil moisture was inadequate**, and to use mulching and protective irrigation. CRIDA also held Karnataka-specific contingency-plan interface meetings. ([NAAS bulletin 13 Jul](https://www.icar-crida.res.in/WDU/2026/JULY_2026/NAAS-Bulletin-13-July-2026.pdf))
- **TNAU** published district-level forecasts for the 2026 southwest monsoon in May, for example Coimbatore at −15% and Erode at −11%. ([TNAU SWM 2026](https://agritech.tnau.ac.in/tnaupressnotes/pdf/2026/TNAU%20District%20level%20seasonal%20rainfall%20forecast%20for%20Southwest%20Monsoon,%202026%20-%20Eng.pdf))
- **Outcome.** Karnataka was 30–39% deficient by mid-July and declared 101 taluks drought-hit on 27 August. Later reports put the count at about 177 taluks and the season deficit at about 35%. Mysuru, Mandya and Chamarajanagar were among the worst hit. ([ETV Bharat](https://www.etvbharat.com/en/state/karnataka-declares-101-taluks-drought-hit-amid-severe-rainfall-deficit-enn26082705096), [ThePrint](https://theprint.in/india/cm-shivakumar-urges-pm-to-depute-central-team-to-assess-drought-in-ktaka/2986635/), [Siasat](https://www.siasat.com/rain-deficit-worsens-in-karnataka-26-more-taluks-face-drought-3538183/))

**Why it didn't reach the farmer.** IMD shut down all 199 District Agromet Units in 2024. These were the block-level advisory teams at KVKs. A revival was announced in January 2025, but **I could not confirm that any units are working again in 2026** ([Tribune](https://www.tribuneindia.com/news/india/shut-down-in-2024-centre-mulls-reviving-weather-advisory-units-for-farmers)). The warnings stayed as English PDFs and national press releases, and nobody turned them into village-level advice. That gap is the one OneRoot can fill.

**Two honest caveats:**
- An 84% national probability is not a guarantee for one village.
- IMD's June outlook said South Peninsula would be *normal to above normal* in June. Some farmers who sowed on early showers were misled by short-range signals, not by the seasonal forecast.

## 2. How much skill the forecasts actually have (South India)

| Horizon | Skill | What it supports |
|---|---|---|
| 0–5 days | Good for rain/no-rain at district scale. Poor for mm at a single point (convective rain). | Spraying, harvest, copra drying, irrigation timing |
| 6–15 days | Moderate. Use ensemble probabilities, not single numbers. Good at spotting dry spells. | Hold or go on sowing, protective irrigation |
| Weeks 2–4 (extended range) | Week 2 is useful. Weeks 3–4 are marginal and only at subdivision level (monsoon active/break phases). | Readiness: stock seed, line up labour |
| 1–3 months | Low for interior Karnataka. Somewhat better for the Tamil Nadu NE monsoon, which has stronger ENSO/IOD links. | Input-mix planning |
| Season | Modest, but **in strong-ENSO years like 2026 the odds shift a lot**. | Crop portfolio, insurance push, sourcing targets |

**How the app should phrase forecasts:**
- Always give a probability and the baseline. Example: *"7 in 10 chance the season ends below normal (a usual year is 3 in 10)."*
- Use terciles (below/near/above normal).
- Never write "will". Write *"odds favour"* or *"risk is high"*.
- Show the issue date and source on every outlook.
- Keep a **forecast-vs-outcome log**. Trust comes from showing the hits and the misses.

## 3. Free data products (checked by web search)

| Product | Access / format | Update | Resolution | Note |
|---|---|---|---|---|
| **IMD gridded rain, real-time** | `imdlib.get_real_data()` ([docs](https://imdlib.readthedocs.io/en/latest/Usage.html)), GRD to xarray | Daily (provisional) | 0.25° | Best free observed daily rain. Runs on the server, no GEE needed. |
| **IMD rainfall statistics** (district/subdivision, weekly and cumulative departure) | [mausam.imd.gov.in](https://mausam.imd.gov.in/responsive/rainfallinformation_swd.php), HTML scrape | Daily/weekly | District | This is the official "% departure" figure governments act on. |
| **IMD extended range forecast** | Regional PDFs/images, e.g. [erf.pdf](https://mausam.imd.gov.in/mumbai/mcdata/erf.pdf) | Weekly (Thursday) | Subdivision, categories for 2–4 weeks | No API. Scrape or enter weekly. |
| **IMD seasonal forecast** | Press-release PDFs | April, end-May, end-June/July, end-September (NE monsoon) | Region | About 5 manual entries a year |
| **CHIRPS-Prelim** | [GEE community catalog](https://gee-community-catalog.org/projects/chirps_prelim/) | Weekly, under 5 days latency | ~5.5 km pentad | The app currently uses `UCSB-CHG/CHIRPS/PENTAD` (final run, weeks of lag). Keep it for 1981+ normals and SPI. |
| **GPM IMERG Early/Late V07** | NASA GES DISC (free Earthdata login) ([catalog](https://www.earthdata.nasa.gov/data/catalog/ges-disc-gpm-3imergde-07)) | About 4 h (Early) / 14 h (Late) latency | 0.1° | Gap-filler when IMD is late |
| **ECMWF SEAS5 + EC46 via Open-Meteo** | `seasonal-api.open-meteo.com/v1/seasonal` ([docs](https://open-meteo.com/en/docs/seasonal-forecast-api)), JSON | EC46 daily; SEAS5 monthly (5th) | 36 km, 51 members, weekly/monthly anomalies, exceedance probabilities | **Licence problem:** Open-Meteo's free tier is **non-commercial only** ([pricing](https://open-meteo.com/en/pricing)). This also applies to the existing `api.open-meteo.com` calls in `core/weather.py`. |
| **ECMWF open data, direct** | CC-BY-4.0 since 1 October 2025, commercial use allowed ([roadmap](https://www.ecmwf.int/node/29013)) | Per run | 0.25° ENS | Clean-licence route for 15-day ensembles. Seasonal via Copernicus CDS (free registration; licence terms not re-verified). |
| **NOAA CPC ENSO / BoM IOD** | [CPC](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) monthly (2nd Thursday); BoM Climate Driver Update fortnightly (current URL not confirmed) | Monthly / fortnightly | Index | Manual feed for the seasonal risk card |
| **KSNDMC** | [ksndmc.org](https://ksndmc.org) Varunamitra; SMS covers hobli/GP 24-hour rain; [OpenCity CSVs](https://data.opencity.in/dataset/karnataka-annual-rainfall-districts-taluks-and-hoblis) | Daily | About 1,530 telemetric gauges | No public API found. Ask KSNDMC for data access. |
| **TNAU district seasonal forecasts** | PDFs at agritech.tnau.ac.in | Pre-season (SW and NE monsoon) | District | Free, and already in local terms |
| **CRIDA District Contingency Plans** | e.g. [Chamarajanagar](https://icar-crida.res.in/CP/Karnataka/GKVK,%20Bangalore/KAR18-CHAMARAJANAGAR%2031.03.2011.pdf); index on [krishi.icar.gov.in](https://krishi.icar.gov.in) | Static (2011 vintage) | District | Confirmed for Chamarajanagar, Hassan, Ramanagara, Chitradurga and Karur (TN). Plans exist for every district, but they are old. Check each against the UAS/TNAU package of practices. |
| **NASA POWER** | power.larc.nasa.gov daily point API | Daily, a few days lag | 0.5° | For ET₀ and water balance. Not re-verified this session. |

## 4. Feature designs

- **Season tracker.** Taluk-level cumulative rain since 1 June (SW monsoon) or 1 October (NE monsoon), against the CHIRPS 1991–2020 normal. Band it in IMD categories: Normal is ±19%, Deficient is −20 to −59%, Large deficient is −60% or worse.
- **Dry-spell counter.** Count consecutive days below 2.5 mm, which is IMD's rainy-day threshold. Show it against the crop stage taken from the existing crop-cycle module.
- **SPI-1 and SPI-3** from the CHIRPS archive. −1.0 is moderate, −1.5 severe, −2.0 extreme.
- **Onset/withdrawal detection, local and agronomic.** Onset is the first day after 1 June (SW) or 10 October (NE) with ≥20 mm in 3 days and **no dry spell of 7 days or more in the next 21 days**. Keep a provisional flag until the 21 days have passed.
- **Sowing window.** Recommend *Sow* when cumulative rain since onset is ≥50–75 mm, surface soil moisture is high, **and** the 15-day ensemble chance of a dry spell of 10+ days is below 40%. Otherwise recommend *Wait*. Past the contingency-plan cutoff date, recommend *Switch*.
- **Contingency matrix.** Map district × delay (2/4/6/8 weeks) × stage (early, mid-season or terminal drought) to the CRIDA recommendation. For example, at a 4-week delay in the southern dry zone, switch from maize to ragi, horse gram or cowpea.
- **Alert thresholds:**
  - **Amber:** departure ≤ −20%, **or** a dry spell of 10+ days in the vegetative stage, **or** 15-day chance of less than 10 mm rain ≥70% during the sowing window.
  - **Red:** departure ≤ −40%, **or** a dry spell of 21+ days (the Drought Manual 2020 trigger is 3–4 weeks; check the exact wording), **or** SPI-3 ≤ −1.5.
  - **Seasonal red:** IMD's chance of below-normal plus deficient is ≥60%.

## 5. Top 8, ranked by decision impact × zero-cost feasibility

1. **Taluk season tracker and dry-spell counter, precomputed nightly.** Uses IMD real-time grid plus CHIRPS normals and a server cron job, so it costs no GEE quota. **About 4 days.** For both groups. *Decision:* go or hold on sowing, revising sourcing volume bands, triggering protective irrigation.
2. **Seasonal risk card in Kannada and Tamil.** Entered by hand from the IMD seasonal forecast, CPC/BoM and TNAU, with probability phrasing and a forecast-vs-outcome log. **About 2 days, then 1 hour a month.** For the decision table first. *Decision:* pre-season input stock mix (short-duration and millet/pulse seed versus maize hybrids), pushing crop-insurance enrolment, setting the sourcing target. **In 2026 this card would have been red by 29 May.**
3. **Push alerts.** Rules from item 1 sent through free channels: a Telegram bot, Google Chat webhooks, email. The WhatsApp Business API charges per message, so it breaks the zero-spend rule. **About 3 days.** For ground staff. *Decision:* field officer visits and briefs villages within 48 hours. This replaces the missing DAMU last mile.
4. **CRIDA contingency matrix for OneRoot's roughly 10–15 districts.** Digitise the plans into structured rows and check them against UAS/TNAU. **About 6 days, mostly data entry.** For ground staff. *Decision:* the farmer's question, "what do I sow now that the rain is X weeks late?"
5. **Sowing-window advisor (Sow / Wait / Switch).** Combines onset detection, soil moisture and the 15-day ensemble. **About 4 days.** For ground staff. *Decision:* timing of seed and fertiliser dispatch to input stores.
6. **Extended-range panel (weeks 1–4/6).** Use the weekly IMD extended-range categories, or EC46 weekly anomalies once the licence is resolved. **About 2–3 days.** For the decision table. *Decision:* shift stock between stores, line up harvest and procurement logistics.
7. **Crop-stress early warning.** Monthly SPI-3 plus NDVI/VCI anomaly per taluk, one GEE batch run for the whole area. **About 4 days.** For the decision table. *Decision:* cut procurement estimates, prepare insurance claims, plan fodder for the dairy pool.
8. **Official-advisory feed.** Latest CRIDA bulletin, IMD/GKMS district advisory and KSNDMC hobli rain shown on each village page. **About 2 days.** For ground staff. *Decision:* staff pass on government advice with a source they can cite, which builds credibility with farmers.

**Fix first:** settle the Open-Meteo commercial-licence question. Either buy a plan, which breaks zero-spend, or move to ECMWF open data under CC-BY-4.0.

## Questions for the OneRoot owner

1. Which crops and sowing dates did the complaining farmer's village actually choose in 2026? Was the sowing decision made in April–May (pre-monsoon crops) or in July? That tells us whether the seasonal or the in-season warning would have changed it.
2. When a warning goes out, what can OneRoot actually *offer*? Short-duration or millet seed in stock, credit, buy-back for alternative crops? An alert with no available action erodes trust.
3. Are you willing to make a field officer accountable for passing on each red alert within 48 hours, with an acknowledgement logged in the app? Last-mile delivery is the gap 2026 exposed.
