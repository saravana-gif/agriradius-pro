/**
 * Karnataka irrigated vs rain-fed cropland — Google Earth Engine
 * ---------------------------------------------------------------
 * Paste into https://code.earthengine.google.com
 *
 * THE CORE IDEA
 * Karnataka's interior gets ~500-900 mm, essentially all of it in the SW monsoon
 * (Jun-Oct) plus some NE monsoon (Oct-Nov) in the south-east. Between roughly
 * mid-February and mid-May there is effectively NO rain. Any actively green,
 * non-perennial cropland in that window is being irrigated. That physical fact
 * is far more robust than any spectral threshold.
 *
 * THE TRAP YOU MUST AVOID
 * Rabi jowar / chickpea / safflower on black cotton soil (vertisols) in
 * Vijayapura, Bagalkot, Kalaburagi, Bidar and Vijayanagara is RAIN-FED — sown
 * Sep-Oct into wet vertisols and matured on stored soil moisture. A naive
 * "green in rabi => irrigated" rule will mislabel a large share of north
 * Karnataka. Hence: SUMMER (Feb-May) is the primary discriminator, rabi is a
 * weak secondary feature only.
 *
 * WHAT PUBLISHED KARNATAKA WORK ACHIEVED
 * Berambadi watershed (Gundlupet taluk, Chamarajanagar), 30 m Landsat, rabi +
 * summer only, NDVI+NDMI+EVI combined, SVM, per-parcel: kappa > 0.9.
 * Individual indices alone performed poorly — the COMBINATION mattered.
 * Multi-sensor NDVI at 5 m over field boundaries: kappa 0.62-0.96.
 * Expect 80-90% in interior/north Karnataka, only 60-75% in coastal Karnataka,
 * Malnad and the Western Ghats where rain keeps everything green year-round.
 * Build a district-stratified model, not one statewide model.
 */

// ============================================================ 0. AOI + SEASONS
var karnataka = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM1_NAME', 'Karnataka'));

// Optional: restrict to one taluk while prototyping.
// Berambadi (Gundlupet, Chamarajanagar) is the published benchmark site.
var aoi = karnataka;

var YEAR = 2025;   // "crop year" — summer window falls in the calendar year after kharif sowing

// Karnataka season convention used by the Kabini / Berambadi studies:
var SEASONS = {
  kharif: [ee.Date.fromYMD(YEAR - 1, 5, 15), ee.Date.fromYMD(YEAR - 1, 9, 15)],  // rain confounds — crop type only
  rabi:   [ee.Date.fromYMD(YEAR - 1, 9, 15), ee.Date.fromYMD(YEAR,     1, 15)],  // WEAK: vertisol false positives
  summer: [ee.Date.fromYMD(YEAR,     1, 15), ee.Date.fromYMD(YEAR,     5, 15)]   // PRIMARY SIGNAL
};

// ============================================================ 1. CROPLAND MASK
var gcep = ee.Image('projects/sat-io/open-datasets/GFSAD/GCEP30');   // 30 m, 2015
var cropMask30 = gcep.eq(2);

var dw = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')
  .filterBounds(aoi)
  .filterDate(SEASONS.kharif[0], SEASONS.summer[1])
  .select('label').mode().eq(4);                                      // 4 = crops

var cropland = cropMask30.or(dw).selfMask().rename('cropland');

// ============================================================ 2. SENTINEL-2 FEATURES
function maskS2(img) {
  var scl = img.select('SCL');
  var ok = scl.neq(3).and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10)).and(scl.neq(11));
  return img.updateMask(ok).divide(10000)
            .copyProperties(img, ['system:time_start']);
}

function s2Indices(img) {
  var ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI');
  var ndmi = img.normalizedDifference(['B8', 'B11']).rename('NDMI');   // moisture — decisive at Berambadi
  var evi  = img.expression(
      '2.5*((N-R)/(N+6*R-7.5*B+1))',
      {N: img.select('B8'), R: img.select('B4'), B: img.select('B2')}).rename('EVI');
  return ndvi.addBands(ndmi).addBands(evi)
             .copyProperties(img, ['system:time_start']);
}

function seasonS2(name) {
  var d = SEASONS[name];
  var col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(aoi).filterDate(d[0], d[1])
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 60))
    .map(maskS2).map(s2Indices);
  var med = col.median().rename([name + '_NDVI_med', name + '_NDMI_med', name + '_EVI_med']);
  var std = col.reduce(ee.Reducer.stdDev())
               .rename([name + '_NDVI_std', name + '_NDMI_std', name + '_EVI_std']);
  var p90 = col.select('NDVI').reduce(ee.Reducer.percentile([90]))
               .rename(name + '_NDVI_p90');
  // seasonal cumulative NDVI — the feature that carried the Berambadi models
  var cum = col.select('NDVI').sum().rename(name + '_NDVI_cum');
  return med.addBands(std).addBands(p90).addBands(cum);
}

// ============================================================ 3. SENTINEL-1 FEATURES
// SAR sees through monsoon cloud. Published unsupervised rule for irrigation
// EVENTS: change in plot-mean VV between consecutive passes,
//   <= -0.5 dB -> no irrigation;  >= +1.0 dB -> probable irrigation event.
// Tested on plots 0.1-65 ha, ~86% overall discrimination.
// Constellation status as of Aug 2026: S1B failed 23 Dec 2021, but S1C (launched
// 5 Dec 2024, operational May 2025) and S1D (launched 4 Nov 2025, operational
// from mid-April 2026) have restored a SIX-DAY exact repeat cycle. Older write-ups
// saying "12-day revisit" are out of date. 6 days makes individual irrigation-event
// detection viable again, not just seasonal classification.
function seasonS1(name) {
  var d = SEASONS[name];
  var col = ee.ImageCollection('COPERNICUS/S1_GRD')
    .filterBounds(aoi).filterDate(d[0], d[1])
    .filter(ee.Filter.eq('instrumentMode', 'IW'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
    .select(['VV', 'VH']);
  var med = col.median().rename([name + '_VV_med', name + '_VH_med']);
  var std = col.reduce(ee.Reducer.stdDev()).rename([name + '_VV_std', name + '_VH_std']);
  var ratio = med.select(name + '_VV_med').subtract(med.select(name + '_VH_med'))
                 .rename(name + '_VVVH');
  return med.addBands(std).addBands(ratio);
}

// ============================================================ 4. FEATURE STACK
// OPTION A — hand-engineered phenology (interpretable, proven in Karnataka)
var stackA = seasonS2('summer').addBands(seasonS2('rabi')).addBands(seasonS2('kharif'))
             .addBands(seasonS1('summer')).addBands(seasonS1('rabi'));

// OPTION B — Google Satellite Embedding (AlphaEarth). 64 bands at 10 m that
// already encode crop phenology + climate. Usually competitive or better with
// far less work, and far fewer lines of code. Try this FIRST.
var emb = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
  .filterDate(YEAR + '-01-01', YEAR + '-12-31').filterBounds(aoi).mosaic();

var USE_EMBEDDING = true;
var features = USE_EMBEDDING ? emb : stackA;

// ============================================================ 5. PRIORS
// 5a. Cropping intensity — in semi-arid interior Karnataka (Chitradurga,
//     Tumakuru, Kolar, Vijayapura, Kalaburagi, Raichur, Ballari) rainfall
//     CANNOT support double/triple cropping, so GCI30 >= 2 is near-conclusive
//     evidence of irrigation. Often a better indicator than actual irrigation products.
var gci = ee.Image('projects/sat-io/open-datasets/GCI30').rename('cropping_intensity');
var multiCrop = gci.gte(2).and(gci.neq(127));

// 5b. Existing global irrigation products, for comparison / weak labels
var lgrip = ee.Image('projects/sat-io/open-datasets/GFSAD/LGRIP30');   // 2=irrigated 3=rainfed
var lgripIrr = lgrip.eq(2), lgripRain = lgrip.eq(3);

var wcIrr = ee.ImageCollection('ESA/WorldCereal/2021/MODELS/v100')
  .filter(ee.Filter.eq('product', 'irrigation'))
  .filterBounds(aoi).mosaic().select('classification').eq(100);
// NOTE: WorldCereal is deliberately conservative and is believed to UNDER-map
// Asia. It has no published accuracy metrics. Lower bound only.

// ============================================================ 6. PARCEL-LEVEL AGGREGATION
// EVERY Karnataka study that reached kappa > 0.9 aggregated to field boundaries
// first. Pixel-level classification on 1 ha fields will disappoint you.
//
// Parcel sources, best first:
//   1. KGIS cadastral polygons via KSRSAC (see 03_kgis_latlong_to_survey.py)
//   2. Your own segmentation of Sentinel-2 (SNIC below) where cadastre is missing
//      — recall only ~61% of Karnataka hissa maps are georeferenced.
var seeds = ee.Algorithms.Image.Segmentation.seedGrid(24);
var snic = ee.Algorithms.Image.Segmentation.SNIC({
  image: seasonS2('summer').select(['summer_NDVI_med', 'summer_NDMI_med', 'summer_EVI_med']),
  size: 24, compactness: 1, connectivity: 8, neighborhoodSize: 128, seeds: seeds
});
var parcels = snic.select('clusters');

// Replace with your real cadastre when you have it:
// var parcels = ee.FeatureCollection('users/YOU/kgis_parcels_karnataka');

var parcelFeatures = features.addBands(parcels)
  .reduceConnectedComponents({reducer: ee.Reducer.mean(), labelBand: 'clusters'})
  .updateMask(cropland);

// ============================================================ 7. TRAINING
// THE HARD REQUIREMENT: local labels. Published Karnataka work is explicit that
// generic NDVI thresholds do NOT transfer — "it is unlikely that generic ranges
// of NDVI might allow for classification without ground observations."
//
// Where labels come from, best first:
//   1. Karnataka Crop Survey (Bele Sameekshe) — per survey number, per season,
//      GPS-tagged, records the type of irrigation adopted. Needs a Dept of
//      Agriculture MoU. Millions of labels. This is the real answer.
//   2. Bhoomi RTC Khushki (dry) / Tari (wet) / Bagayat (garden) extent split,
//      pulled at ~Rs 15-25 per parcel. 2,000-3,000 parcels is enough to start.
//   3. Your own field staff dropping labelled pins. Cheapest to start, and
//      the labels are current.
//
// var labels = ee.FeatureCollection('users/YOU/karnataka_irrigation_labels');
// property 'irrigated': 1 = irrigated (tari/bagayat), 0 = rain-fed (khushki)
var labels = ee.FeatureCollection([]);   // <-- REPLACE

var training = parcelFeatures.sampleRegions({
  collection: labels, properties: ['irrigated'], scale: 10, tileScale: 4, geometries: false
});

var split = training.randomColumn('r', 42);
var train = split.filter(ee.Filter.lt('r', 0.7));
var test  = split.filter(ee.Filter.gte('r', 0.7));

var clf = ee.Classifier.smileRandomForest({numberOfTrees: 300, minLeafPopulation: 5})
  .setOutputMode('PROBABILITY')
  .train({features: train, classProperty: 'irrigated',
          inputProperties: parcelFeatures.bandNames()});

var prob = parcelFeatures.classify(clf).rename('irrigation_probability');

// Accuracy — report it stratified by agro-climatic zone, not statewide.
var conf = test.classify(clf.setOutputMode('CLASSIFICATION'))
               .errorMatrix('irrigated', 'classification');
print('Confusion matrix', conf);
print('Overall accuracy', conf.accuracy());
print('Kappa', conf.kappa());

// ============================================================ 8. FUSE THE PRIORS
// Command areas: rasterise the India-WRIS CommandArea GeoJSON from
// 02_wris_command_areas.py and upload as a GEE asset.
// var command = ee.FeatureCollection('users/YOU/wris_command_karnataka');
// var inCommand = ee.Image(0).paint(command, 1);
var inCommand = ee.Image(0);   // <-- REPLACE

var score = prob.multiply(0.55)
  .add(multiCrop.multiply(0.20))        // double/triple cropping in semi-arid districts
  .add(lgripIrr.multiply(0.10))
  .add(wcIrr.multiply(0.05))
  .add(inCommand.multiply(0.10))
  .rename('irrigation_score')
  .updateMask(cropland);

// Water source split: inside a command area -> canal/surface.
// Irrigated but outside -> groundwater (borewell). In Karnataka 56.6% of net
// irrigated area is borewell/tubewell, so this split matters commercially.
var likelyIrrigated = score.gte(0.5);
var sourceClass = ee.Image(0)
  .where(likelyIrrigated.and(inCommand.eq(1)), 1)    // 1 = canal / surface
  .where(likelyIrrigated.and(inCommand.eq(0)), 2)    // 2 = groundwater / borewell
  .updateMask(cropland).rename('water_source');

// ============================================================ 9. DISPLAY + EXPORT
Map.centerObject(aoi, 7);
Map.addLayer(cropland, {palette: ['cccccc']}, 'Cropland mask', false);
Map.addLayer(lgrip.updateMask(lgrip.gte(2)),
  {min: 2, max: 3, palette: ['1f78b4', 'e08214']}, 'LGRIP30 (blue=irr, orange=rain)', false);
Map.addLayer(wcIrr.selfMask(), {palette: ['00b0f0']}, 'WorldCereal irrigation 2021', false);
Map.addLayer(multiCrop.selfMask(), {palette: ['7fbf7b']}, 'GCI30 multi-crop (irrigation proxy)', false);
Map.addLayer(score, {min: 0, max: 1, palette: ['f7f7f7', 'fddbc7', 'ef8a62', 'b2182b']},
             'Irrigation score');
Map.addLayer(sourceClass.selfMask(), {min: 1, max: 2, palette: ['2166ac', 'd6604d']},
             'Water source: blue=canal, red=borewell');

// Per-village statistics — the deliverable your field staff actually use.
// var villages = ee.FeatureCollection('users/YOU/kgis_villages_karnataka');
// var byVillage = score.gte(0.5).multiply(ee.Image.pixelArea()).divide(10000)
//   .addBands(cropland.multiply(ee.Image.pixelArea()).divide(10000))
//   .reduceRegions({collection: villages, reducer: ee.Reducer.sum(), scale: 10, tileScale: 8});
// Export.table.toDrive({collection: byVillage,
//   description: 'karnataka_village_irrigated_ha', fileFormat: 'CSV'});

Export.image.toDrive({
  image: score.multiply(100).toUint8(),
  description: 'karnataka_irrigation_score_' + YEAR,
  region: aoi.geometry(), scale: 10, maxPixels: 1e13,
  fileFormat: 'GeoTIFF', formatOptions: {cloudOptimized: true}
});

// ============================================================ REFERENCE ASSETS
// projects/sat-io/open-datasets/GFSAD/LGRIP30      30 m, 2015, 2=irrigated 3=rainfed
// projects/sat-io/open-datasets/GFSAD/GCEP30       30 m cropland extent
// projects/sat-io/open-datasets/GCI30              30 m cropping intensity
// ESA/WorldCereal/2021/MODELS/v100                 10 m, product=='irrigation'
// GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL             10 m, 64 bands
// COPERNICUS/S2_SR_HARMONIZED  /  COPERNICUS/S1_GRD
// GOOGLE/DYNAMICWORLD/V1                           10 m near-real-time land cover
// USGS/GFSAD1000_V1                                1 km — context only
// NASA/GRACE/MASS_GRIDS/V04/MASCON                 ~300 km — narrative only, NOT field level
//
// NOT in GEE, download separately:
//   GMIE-100 (100 m, 2017-19)  https://doi.org/10.7910/DVN/HKBAQQ
//   Irrigation water sources (60 m, groundwater vs surface)  https://doi.org/10.6084/m9.figshare.c.7318916
//   Ambika et al. India 250 m 2000-2015  https://dx.doi.org/10.6084/m9.figshare.3790611.v1
//   ICRISAT India 10 m 2024-25 — ask ICRISAT for the asset ID
