# Nairobi exposure value discrepancy

The supplied `data/exposure_nairobi_with_hazard.csv` and `data/exposure_nairobi_synthetic.csv` contain the same 600 base exposure rows. The value comparison below uses the supplied prepared CSV without changing it.

| Measure | Supplied CSV | `Dataset_Metadata.docx` |
|---|---:|---:|
| Minimum `tiv_kes` | 410,000 | 40,000 |
| Median `tiv_kes` | 5,192,500 | 520,000 |
| Maximum `tiv_kes` | 1,592,010,000 | 159,200,000 |
| Total `tiv_kes` | 63,635,075,000 | 6,363,470,000 |
| Sum of `floor_area_m2 × cost_per_m2_kes` | 6,363,503,700 | Described as basis of TIV |

The supplied TIV total is approximately 10.000006 times the area-times-cost total. All 600 rows differ from area-times-cost by more than 10%. The metadata's TIV total is close to the area-times-cost total, but no source in this workspace explains why the CSV has approximately ten times those values. This remains an **unresolved input discrepancy**, not a confirmed correction factor.

The baseline uses the supplied `tiv_kes` so its results are traceable to the file. `flood-cat sensitivity` reruns the identical portfolio with area-times-cost values as an explicit alternative. Both results must be shown with their value basis; neither should be presented as a verified insured sum without source confirmation.

The 0–1 hazard values in the prepared CSV are sampled from the supplied GeoTIFFs. Those GeoTIFFs are relative susceptibility proxies, not observed flood depths. The default vulnerability curves and tier return periods are illustrative or assumed, respectively. The resulting losses and EP points are suitable for a prototype comparison, not calibrated underwriting estimates.
