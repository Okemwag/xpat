// Sentinel-1 flood extent for Nairobi — paste into the Google Earth Engine Code Editor and run.
// Method: UN-SPIDER Recommended Practice "Flood Mapping and Damage Assessment Using Sentinel-1 SAR Data in Google Earth Engine"
// (un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping/step-by-step).
// Output: a GeoTIFF with 1 = flooded, 0 = dry, nodata = masked. Upload it on the "Hazard checks" page (Satellite flood check)
// or run: uv run flood-cat satellite-check <file.tif>
// The flood map is REAL (observed); radar under-detects water among buildings, so dense urban flooding is underestimated.

var aoi = ee.Geometry.Rectangle([36.60, -1.45, 37.00, -1.10]);  // the hazard maps' extent
// Event: the March–May 2024 long rains (WRI 2026: 400–660 mm, heaviest in two decades). Adjust both windows for other events.
var before = ['2024-01-01', '2024-02-28'];
var after = ['2024-04-20', '2024-05-10'];
var polarization = 'VH';      // UN-SPIDER: VH is more sensitive to changes on the land surface
var passDirection = 'DESCENDING';  // must match between the two periods; switch if a period has no scenes
var threshold = 1.25;         // UN-SPIDER default change ratio (after ÷ before)
var smoothing = 50;           // metres, speckle filter radius

var collection = ee.ImageCollection('COPERNICUS/S1_GRD')
  .filter(ee.Filter.eq('instrumentMode', 'IW'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation', polarization))
  .filter(ee.Filter.eq('orbitProperties_pass', passDirection))
  .filter(ee.Filter.eq('resolution_meters', 10))
  .filterBounds(aoi)
  .select(polarization);

var beforeImage = collection.filterDate(before[0], before[1]).mosaic().clip(aoi).focal_mean(smoothing, 'circle', 'meters');
var afterImage = collection.filterDate(after[0], after[1]).mosaic().clip(aoi).focal_mean(smoothing, 'circle', 'meters');
var flooded = afterImage.divide(beforeImage).gt(threshold);

// Permanent water: JRC Global Surface Water seasonality > 10 months.
var permanent = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('seasonality').gte(10).unmask(0);
flooded = flooded.where(permanent, 0);
// Slopes over 5% (HydroSHEDS DEM), as in the practice.
var slope = ee.Algorithms.Terrain(ee.Image('WWF/HydroSHEDS/03VFDEM')).select('slope');
flooded = flooded.where(slope.gt(5), 0);
// Remove specks: flooded pixels connected to 8 or fewer neighbours.
var connections = flooded.selfMask().connectedPixelCount();
flooded = flooded.where(connections.lte(8), 0).unmask(0).updateMask(afterImage.mask());

Map.centerObject(aoi, 11);
Map.addLayer(flooded.selfMask(), {palette: ['0000ff']}, 'Flooded (UN-SPIDER method)');

Export.image.toDrive({
  image: flooded.toByte(),
  description: 'nairobi_sentinel1_flood_2024',
  region: aoi,
  scale: 10,
  crs: 'EPSG:4326',
  maxPixels: 1e10
});
