/**
 * Karnataka — crop type, plantations and forest vs farmland
 * ---------------------------------------------------------
 * Paste into https://code.earthengine.google.com
 * Companion to 04_gee_karnataka_irrigation.js
 *
 * WHAT THIS DOES
 *  A. Builds a forest mask that does NOT swallow your coffee, arecanut, mango
 *     and coconut blocks — the single biggest failure mode in Karnataka.
 *  B. Separates perennial (orchard / plantation) from annual cropland.
 *  C. Sets up per-parcel phenology features for annual crop-type classification.
 *
 * THE CORE PROBLEM, STATED PLAINLY
 * FSI defines forest cover as canopy >10% over >1 ha "irrespective of ownership
 * and legal status, and irrespective of whether the trees are orchards, bamboo
 * or palm." So Kodagu/Chikkamagaluru coffee, Shivamogga/Dakshina Kannada areca,
 * and coastal coconut all read as "forest" in ISFR, Hansen, WorldCover, everything.
 * And NO satellite product can tell you LEGAL forest status. Ever. For that you
 * need KGIS/KFD boundaries — see sheet 3 of the workbook.
 */

// ============================================================ 0. AOI
var karnataka = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM1_NAME', 'Karnataka'));
var aoi = karnataka;
var YEAR = 2025;

// ============================================================ 1. FOREST — the good mask
// JRC Global Forest Cover 2020 is the best free layer for your problem because
// it EXPLICITLY EXCLUDES agricultural plantations (oil palm, cocoa, coffee,
// rubber, soya) and land under agricultural or urban use. 10 m. That one design
// choice removes most of the Karnataka false-positive problem for free.
var gfc = ee.Image('JRC/GFC2020/V3').select('Map');
var forest2020 = gfc.eq(1).selfMask();

// Forest SUBTYPES — 1 = naturally regenerating, 10 = primary, 20 = planted forest.
// Built for EUDR. If you ever export coffee to the EU, this pair is the reference
// regulators expect.
var subtypes = ee.Image('JRC/GFC2020_subtypes/V1');
var naturalForest = subtypes.eq(1).or(subtypes.eq(10));
var plantedForest = subtypes.eq(20);

// WRI SBTN Natural Lands — independent second opinion, 30 m
var natural = ee.Image('WRI/SBTN/naturalLands/v1_1/2020').select('natural');

// ============================================================ 2. TREE COVER THAT IS *NOT* FOREST
// This is the layer you actually want: canopy present, but excluded from GFC2020.
// In Karnataka that is overwhelmingly arecanut, coconut, coffee, mango, cashew,
// rubber and eucalyptus/acacia woodlots — i.e. FARMLAND WITH TREES.
var wc = ee.Image('ESA/WorldCover/v200').select('Map');
var treeCover = wc.eq(10);            // 10 = tree cover
var cropland  = wc.eq(40);            // 40 = cropland

var treesNotForest = treeCover.and(gfc.neq(1)).selfMask()
  .rename('probable_tree_crop');

// ============================================================ 3. CANOPY STRUCTURE — the real discriminator
// Orchards and plantations are REGULAR. Natural forest is not. At 1 m you can
// see the grid. This is what separates an areca garden from a Western Ghats
// evergreen patch when their spectra are near-identical.
// (Community catalogue asset, not the official GEE catalogue.)
var ch = ee.Image('projects/sat-io/open-datasets/facebook/meta-canopy-height');
var chETH = ee.Image('users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1');

// Local standard deviation of canopy height: LOW over a planted grid of uniform
// trees, HIGH over multi-storey natural forest.
var chStd = ch.reduceNeighborhood({
  reducer: ee.Reducer.stdDev(),
  kernel: ee.Kernel.square({radius: 15, units: 'meters'})
}).rename('canopy_height_sd');

var chMean = ch.reduceNeighborhood({
  reducer: ee.Reducer.mean(),
  kernel: ee.Kernel.square({radius: 15, units: 'meters'})
}).rename('canopy_height_mean');

// Rough plantation flag: trees present, canopy tall enough to be a crop tree,
// but structurally uniform. TUNE THE THRESHOLDS ON KNOWN AREAS FIRST —
// Shivamogga/Sagara for areca, Kodagu for coffee, Tumakuru for coconut.
var plantationLike = treeCover
  .and(chMean.gt(4)).and(chMean.lt(25))
  .and(chStd.lt(2.5))
  .selfMask().rename('plantation_like');

// ============================================================ 4. PERENNIAL vs ANNUAL CROPLAND
// Perennials (banana, orchard, areca, coffee, sugarcane ratoon) never fully
// senesce. Annuals do. Minimum annual NDVI is the cleanest separator.
function maskS2(img) {
  var scl = img.select('SCL');
  var ok = scl.neq(3).and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10)).and(scl.neq(11));
  return img.updateMask(ok).divide(10000).copyProperties(img, ['system:time_start']);
}

var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(aoi)
  .filterDate(YEAR + '-01-01', YEAR + '-12-31')
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 60))
  .map(maskS2)
  .map(function (i) {
    return i.normalizedDifference(['B8', 'B4']).rename('NDVI')
            .copyProperties(i, ['system:time_start']);
  });

var ndviMin   = s2.min().rename('ndvi_min');
var ndviMax   = s2.max().rename('ndvi_max');
var ndviMean  = s2.mean().rename('ndvi_mean');
var ndviRange = ndviMax.subtract(ndviMin).rename('ndvi_range');

// Perennial: stays green all year. Banana, orchard, areca, coffee, coconut.
var perennialCrop = ndviMin.gt(0.35).and(cropland.or(treeCover)).selfMask();
// Annual: big swing between peak and bare. Maize, vegetables, pulses, cotton.
var annualCrop    = ndviRange.gt(0.35).and(ndviMin.lt(0.30)).and(cropland).selfMask();

// ============================================================ 5. CROPPING FREQUENCY -> vegetables
// Short-cycle vegetables green up and senesce 2-3 times a year, out of phase
// with the monsoon calendar. You will not tell tomato from brinjal at 10 m over
// a 1 ha plot — nobody can. But you CAN detect "short-cycle irrigated vegetable",
// then use the Karnataka DES taluk area file to allocate that class to likely
// species by taluk. That combination is the practical answer.
var gci = ee.Image('projects/sat-io/open-datasets/GCI30').rename('cropping_intensity');
var multiCrop = gci.gte(2).and(gci.neq(127));

// ============================================================ 6. FEATURE STACK FOR CROP TYPE
// Monthly NDVI composites are the standard crop-type backbone.
var months = ee.List.sequence(1, 12);
var monthly = ee.ImageCollection.fromImages(months.map(function (m) {
  var comp = s2.filter(ee.Filter.calendarRange(m, m, 'month')).median();
  return comp.rename(ee.String('ndvi_m').cat(ee.Number(m).format('%02d')))
             .set('month', m);
})).toBands();

// Or skip all of the above and use the embedding — 64 bands that already encode
// phenology. For crop type specifically this is usually the better starting point.
var emb = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
  .filterDate(YEAR + '-01-01', YEAR + '-12-31').filterBounds(aoi).mosaic();

var cropFeatures = emb
  .addBands(ndviMin).addBands(ndviMax).addBands(ndviRange).addBands(ndviMean)
  .addBands(chMean).addBands(chStd)
  .addBands(gci);

// ============================================================ 7. TRAINING LABELS
// Realistic accuracy expectations for Karnataka, crop by crop (see workbook sheet 4):
//   Maize            GOOD      — distinct C4 phenology; separable from rice/cotton,
//                                harder against sorghum and other irrigated row crops
//   Banana           GOOD      — year-round high NDVI, no senescence; CHAMAN maps it officially
//   Orchards         GOOD      — as a class; species needs crown-spacing analysis
//   Plantations      GOOD      — as a class; structure, not spectra, is the discriminator
//   Vegetables       POOR      — as species; MODERATE as "short-cycle irrigated"
//   Turmeric         POOR      — small plots, intercropped, spectrally close to ginger
//   Flowers          VERY POOR — tiny plots, much of it under polyhouse/shade net.
//                                Detect POLYHOUSES instead (bright geometric rectangles);
//                                polyhouse density is a better commercial signal anyway.
//
// Label sources, best first:
//   1. Karnataka Crop Survey (Bele Sameekshe) — per survey number, per season, geotagged. MoU needed.
//   2. PMFBY CCE gram-panchayat records — free, has crop_name AND irrigation_type. See script 05.
//   3. Your own field staff dropping labelled pins.
// var labels = ee.FeatureCollection('users/YOU/karnataka_crop_labels');  // property 'crop'
var labels = ee.FeatureCollection([]);   // <-- REPLACE

var training = cropFeatures.sampleRegions({
  collection: labels, properties: ['crop'], scale: 10, tileScale: 4
});
var clf = ee.Classifier.smileRandomForest(300)
  .train({features: training, classProperty: 'crop',
          inputProperties: cropFeatures.bandNames()});
// var cropMap = cropFeatures.classify(clf);

// ============================================================ 8. DISPLAY
Map.centerObject(aoi, 7);
Map.addLayer(forest2020, {palette: ['1a5e20']}, 'JRC GFC2020 forest (excl. agri-plantations)');
Map.addLayer(naturalForest.selfMask(), {palette: ['0b3d0b']}, 'Natural / primary forest', false);
Map.addLayer(plantedForest.selfMask(), {palette: ['8fbc8f']}, 'Planted forest', false);
Map.addLayer(treesNotForest, {palette: ['d2691e']}, 'Trees but NOT forest = probable tree crop');
Map.addLayer(plantationLike, {palette: ['ff8c00']}, 'Structurally uniform canopy = plantation-like', false);
Map.addLayer(perennialCrop, {palette: ['2e8b57']}, 'Perennial crop (banana / orchard / areca)', false);
Map.addLayer(annualCrop, {palette: ['daa520']}, 'Annual crop (maize / veg / pulses)', false);
Map.addLayer(multiCrop.selfMask(), {palette: ['7fbf7b']}, 'Multi-cropped (GCI30 >= 2)', false);
Map.addLayer(ch, {min: 0, max: 30, palette: ['ffffff', 'a1d99b', '31a354', '00441b']},
             'Canopy height 1 m (Meta)', false);

// ============================================================ 9. PER-TALUK / PER-VILLAGE EXPORT
// This is what your field staff actually consume. Join on the KGIS taluk_code
// that the Karnataka DES horticulture files already carry (see script 05) —
// no fuzzy name matching needed.
// var taluks = ee.FeatureCollection('users/YOU/kgis_taluks_karnataka');
// var ha = ee.Image.pixelArea().divide(10000);
// var stats = perennialCrop.gt(0).multiply(ha).rename('perennial_ha')
//   .addBands(annualCrop.gt(0).multiply(ha).rename('annual_ha'))
//   .addBands(treesNotForest.gt(0).multiply(ha).rename('tree_crop_ha'))
//   .addBands(forest2020.gt(0).multiply(ha).rename('forest_ha'))
//   .reduceRegions({collection: taluks, reducer: ee.Reducer.sum(), scale: 10, tileScale: 8});
// Export.table.toDrive({collection: stats,
//   description: 'karnataka_taluk_croptype_forest_ha', fileFormat: 'CSV'});

// ============================================================ REFERENCE
// FOREST
//   JRC/GFC2020/V3                          10 m, 2020, EXCLUDES agri-plantations  <-- start here
//   JRC/GFC2020_subtypes/V1                 10 m, 1=natural regen 10=primary 20=planted
//   WRI/SBTN/naturalLands/v1_1/2020         30 m, natural vs converted
//   UMD/hansen/global_forest_change_2025_v1_13   CURRENT (v1_12 is deprecated)
//     ^ WARNING: Hansen "loss" is NOT deforestation in Karnataka. Areca and coffee
//       shade-tree replanting, eucalyptus/acacia harvest rotations and rubber
//       felling all register as loss. Never present it as deforestation.
//   ESA/WorldCover/v200                     10 m, 10=tree 40=crop 95=mangrove
//   LANDSAT/MANGROVE_FORESTS                Uttara Kannada / Udupi / Dakshina Kannada
//   JRC Tropical Moist Forest: projects/JRC/TMF/v1_<year>/...  — LIST THE FOLDER FIRST,
//     the version suffix could not be confirmed and Karnataka coverage is partial
//     (Western Ghats evergreen yes; Deccan dry deciduous no).
// CANOPY STRUCTURE
//   projects/sat-io/open-datasets/facebook/meta-canopy-height   1 m  <-- the orchard discriminator
//   users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1              10 m
// CROP
//   COPERNICUS/S2_SR_HARMONIZED | COPERNICUS/S1_GRD
//   GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL | GOOGLE/DYNAMICWORLD/V1
//   projects/sat-io/open-datasets/GCI30     cropping intensity
// NOT IN GEE
//   CHAMAN (banana, citrus, mango — official, Karnataka covered): https://bhuvan-app1.nrsc.gov.in/chaman/
//   NRSC LULC50K — the only Indian product with a distinct Plantation class: https://bhuvan-app1.nrsc.gov.in/thematic/
//   FSI Anavaran deforestation alerts (free .zip): https://fsi.nic.in/deforestation-alert-system
