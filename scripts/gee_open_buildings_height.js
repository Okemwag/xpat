// Building heights for Nairobi from Open Buildings 2.5D Temporal v1 — paste into the Google Earth Engine Code Editor and run.
// Dataset: GOOGLE/Research/open-buildings-temporal/v1 (developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1)
// band building_height: metres above terrain, 0–100; yearly 2016–2023; ~4 m effective resolution; CC-BY 4.0 or ODbL.
// Produced by Google's machine-learning model from Sentinel-2, so filled storeys are labelled AI. No height accuracy is published.
// Output: a GeoTIFF of building height (m). Upload it on the Portfolio page (Fill storeys from building heights).

var aoi = ee.Geometry.Rectangle([36.60, -1.45, 37.00, -1.10]);
var year = 2023;
var image = ee.ImageCollection('GOOGLE/Research/open-buildings-temporal/v1')
  .filter(ee.Filter.calendarRange(year, year, 'year'))
  .filterBounds(aoi)
  .mosaic()
  .select('building_height')
  .clip(aoi);

Map.centerObject(aoi, 12);
Map.addLayer(image, {min: 0, max: 30}, 'Building height (m)');

Export.image.toDrive({
  image: image.toFloat(),
  description: 'nairobi_open_buildings_height_' + year,
  region: aoi,
  scale: 4,
  crs: 'EPSG:4326',
  maxPixels: 1e11
});
