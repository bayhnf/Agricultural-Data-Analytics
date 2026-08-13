# Assignment 5 walkthrough: Sentinel-2 cloud masking and NDVI

## Real source and deterministic scene selection

This assignment uses real Copernicus Sentinel-2 Level-2A imagery from the
Element 84 Earth Search `sentinel-2-l2a` collection. The search window is
`2023-06-01T00:00:00Z/2023-08-31T23:59:59Z` over the 25 selected Story
County, Iowa field polygons.

Candidates are sorted client-side by:

1. `eo:cloud_cover` (missing values sort last);
2. acquisition datetime; and
3. scene ID.

For each candidate, the pipeline reads only the SCL window covering the field
bounds, rasterizes the union of all selected fields on that grid, and measures
the share of in-field pixels in valid SCL classes. It selects the first sorted
scene at or above the 70% threshold and records every earlier rejection in
`data/processed/assignment-05/scene.json`.

The selected scene is `S2B_15TVG_20230620_0_L2A`, acquired on June 20, 2023.
Its study-area valid-SCL fraction is 1.000, so there were no rejected
candidates before it.

## SCL cloud mask and grid alignment

The valid classes are:

- 4: vegetation;
- 5: not vegetated;
- 6: water; and
- 7: unclassified.

The excluded classes are 0 (no data), 1 (saturated or defective), 2
(dark-area pixels), 3 (cloud shadow), 8 (medium-probability cloud), 9
(high-probability cloud), 10 (thin cirrus), and 11 (snow or ice).

SCL is delivered at 20 m resolution. It is reprojected onto the 10 m red-band
grid with nearest-neighbor resampling so categorical class values are not
interpolated. Raw red/NIR nodata, invalid SCL classes, pixels outside the
selected fields, non-finite values, and zero NDVI denominators are masked.

## Reflectance and NDVI

Each reflectance asset's own STAC metadata is applied independently:

```text
reflectance = digital_number * scale + offset
```

For the selected scene, both red and NIR report `scale=0.0001` and
`offset=-0.1`. NDVI is then:

```text
NDVI = (NIR - red) / (NIR + red)
```

Finite results are constrained to `[-1, 1]`. The pipeline calculates mean,
median, valid-pixel count, total in-field pixel count, and coverage fraction
for each of the 25 fields using the shared continuous zonal-summary helper.

The real-image outputs are:

- `docs/assets/sentinel_red_band.png`;
- `docs/assets/ndvi_map.png`; and
- `data/processed/assignment-05/field_ndvi.csv`.

## Interpretation and limitations

The field summaries describe one clear-sky acquisition, not seasonal crop
performance. NDVI is sensitive to canopy cover, crop growth stage, soil
background, atmospheric correction, and residual classification errors. A
high value is not a direct yield estimate or management recommendation.

The polygons are 2019 USDA ACPF field-analysis boundaries overlaid on 2023
imagery, so later field splits, merges, or boundary edits are not represented.
SCL validity indicates acceptable classification for this screen; it does not
prove every pixel is free from haze, adjacency effects, or sub-pixel cloud.
Low-signal surface reflectance can produce out-of-range ratios after offset
application, which is why finite NDVI is explicitly clipped to its physical
range.

The committed field summary has 3 of 25 field means and 17 of 25 field medians
pinned at exactly 1.0 after clipping. These saturated fields reach the
dense-canopy ceiling of the NDVI formula and should be treated as "at or above"
ceiling values rather than as precise, rankable measurements within that group.

## Attribution

Contains modified Copernicus Sentinel data (2023), processed by ESA and
accessed through the Element 84 Earth Search public-data catalog.
