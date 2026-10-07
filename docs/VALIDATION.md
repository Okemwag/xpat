# Validation

31 tests passed, including live raster sampling. Baseline CLI, trained-ML CLI and a live loopback API startup/health request succeeded. Docker and CI definitions are supplied but were not executed here.

One upstream Starlette/httpx test-client deprecation warning remains; it does not affect passing tests.

Tested environment:

- fastapi: 0.142.2
- pydantic: 2.13.5
- uvicorn: 0.54.0
- pytest: 9.1.1
- httpx: 0.28.1
- rasterio: 1.5.2
- numpy: 2.3.5
- scikit-learn: 1.8.0

The ML fixture is synthetic; these checks verify code behavior, not Nairobi predictive validity. Actual starter CSVs/GeoTIFFs were not attached.
