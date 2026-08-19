# Final Project Dashboard Enhancement Design

**Date:** 2026-08-19
**Branch:** `feature/final-project-dashboard`
**Assignment:** 9 — Row Crop Intelligence Data Dashboard

## Goal

Complete the supplied final-project rubric by extending the existing public
GitHub Pages dashboard with field and soil filtering, dynamic agronomic
captions, the missing Assignment 3 visualization, final documentation, and
submission screenshots.

The existing deterministic public-data pipeline and static dashboard remain the
source of truth. No second dashboard framework, backend, database, or runtime
AI service will be introduced.

## Approved Scope

The dashboard will continue to use the 25-field Story County dataset already
produced and validated by Assignments 2–8. The PDF's reference to a 200-field
package will be documented as course-template wording rather than silently
changing the established project dataset.

Expanding to 200 fields is excluded because it would require reselection and
reprocessing across Assignments 2–8, not just completion of the final
dashboard.

The supplied products contain crop classification, but no measured or modeled
yield layer. Therefore the PDF's example "Predicted Total Bushels" KPI will not
be invented or estimated from unrelated data; the dashboard will disclose this
limitation and use the available NDVI, crop, weather, and soil KPIs instead.

The PDF names Streamlit and Dash as examples of Python-based BI tools. This
project deliberately keeps its already-published, dependency-free GitHub Pages
dashboard and adds native browser filters. That provides a live, interactive
public URL without a second deployment or runtime service. A Streamlit/Dash
port is excluded unless the instructor explicitly requires a framework rather
than the rubric's interactive behavior.

## Data Contract

`scripts/build_dashboard.py` will keep the existing package KPI fields and add
one sorted `fields` array to `docs/data/dashboard.json`.

Each field record will contain only values needed by filtering, selected KPIs,
and narratives:

- `field_id`
- `area_ha`
- `crop_2023`
- `crop_2023_pixels`
- `soil_type`
- `soil_name`
- `mean_ndvi`
- `ndvi_coverage_fraction`
- `organic_matter_pct`
- `ph_h2o`
- `cec_cmol_kg`
- `carbon_storage_mg_c_ha`

The records will be assembled from existing committed Assignment 2, 5, 7, and
8 products. The builder will reject missing inputs, duplicate IDs, mismatched
field-ID sets, missing values required by the dashboard, and non-finite numeric
values.

The array will be sorted by `field_id` so repeated builds remain deterministic.

## Dashboard Interaction

The current dependency-free GitHub Pages dashboard will gain two native
controls:

- Field ID: all fields or one field.
- Soil Type: all soil types or one dominant SSURGO soil type.

The controls will be disabled until the JSON payload is validated. Both filters
will apply together. A no-match selection will show an explicit empty state
instead of misleading KPI values.

For a matching selection, the dashboard will update:

- field count;
- total acreage or hectares;
- dominant 2023 crop;
- mean NDVI and NDVI coverage;
- mean organic matter, pH, CEC, and carbon-storage screening estimates.

Scene date and NASA POWER weather values remain package-wide because the source
data are not field-specific. The interface will label them as package-wide
whenever a field or soil filter is active.

The controls will use native labels, keyboard behavior, focus styling, a reset
button, and polite live-status announcements. No custom select component or
JavaScript library is needed for 25 fields.

## Dynamic Agronomic Captions

The assignment asks for AI-assisted code that generates dynamic captions; it
does not require a live language-model API. The implementation will therefore
use deterministic, reviewable templates generated from the selected data.

Narratives will include:

- selection size and dominant crop;
- selected field and dominant soil context when one field is shown;
- the selected mean NDVI;
- a low-NDVI alert when mean NDVI is below `0.3`;
- a watch message from `0.3` through `0.6`;
- a monitoring message above `0.6`;
- pH and organic-matter screening context;
- source limitations appropriate to the selected metrics.

The low-NDVI alert will recommend immediate scouting for possible nutrient,
pest, disease, water, or establishment pressure and comparison with growth
stage and field observations. It will state that one satellite scene cannot
confirm which cause is present and will not claim measured stress or yield
loss.

The copy will state that NDVI is a single-scene canopy signal, CDL is a
satellite classification, and SSURGO values are generalized screening
estimates rather than measured samples or management prescriptions.

## Visualizations

The existing dashboard already presents seven assignment figures. It will also
embed `docs/assets/crop_rotation_patterns.png` from Assignment 3 so the five
explicit rubric categories are visibly represented:

1. EDA relationship or rotation plot;
2. geospatial field/soil map;
3. vegetation/NDVI;
4. weather time series;
5. soil-health metrics.

Existing source attribution, units, alternative text, image dimensions, and
limitations will be retained.

## Documentation and Submission Media

`README.md` will gain:

- a final-project description and live dashboard link;
- the technologies used;
- commands to regenerate and serve the dashboard locally;
- a note explaining the established 25-field scope;
- links to the AI usage summary and screenshots.

`docs/AI_DOCS.md` will honestly summarize how AI assisted with code generation,
testing, review, and documentation; how outputs were verified; and what AI did
not do. It will not contain credentials, private course material, or claims
that the runtime captions call an AI service.

Three to five screenshots will be generated from the completed dashboard,
covering the package overview and different dashboard sections or filter
states. The user will still need to attach the repository URL and screenshots,
add the brief "aha!" final reflection in Google Classroom comments, and submit
the assignment there.

The README branch map will be updated from the earlier `feature/final-dashboard`
entry to `feature/final-project-dashboard`.

## Testing

Production behavior will be added test-first in `tests/test_dashboard.py`.
The failing contract will cover:

- the exact per-field payload schema and deterministic sort order;
- 25 unique matching field IDs across every input;
- rejection of mismatched IDs and non-finite values;
- accessible Field ID and Soil Type controls;
- a reset control and live narrative region;
- the Assignment 3 visualization;
- required narrative thresholds and limitation language;
- README final-project/run instructions and `docs/AI_DOCS.md`.

The existing full unit suite, dashboard builder, repository privacy verifier,
HTML reference checks, and `git diff --check` will run before completion.

## Delivery

Work will be committed on `feature/final-project-dashboard`, pushed to GitHub,
reviewed through a pull request, merged into `main`, and verified on the public
GitHub Pages URL.

## Excluded

- rebuilding Assignments 2–8 for 200 fields;
- Streamlit or Dash duplication;
- a backend, database, authentication, or runtime LLM API;
- synthetic agricultural data;
- automatic Google Classroom submission;
- a recorded video, because the rubric accepts screenshots instead.

→ skipped: a second dashboard framework and 200-field migration; add only if
the instructor explicitly rejects the established 25-field project scope.
