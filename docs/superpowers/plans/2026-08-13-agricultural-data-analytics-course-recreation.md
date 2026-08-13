# Agricultural Data Analytics Course Recreation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a clean, reproducible Assignment 1–8 agricultural data analytics repository and final GitHub Pages dashboard for 25 deterministic Story County, Iowa field-analysis units using only documented public data.

**Architecture:** Short Python 3.12 scripts acquire and transform public vector, raster, weather, and soil sources into small committed products. Notebooks consume those products and produce the course figures; a plain HTML/CSS dashboard reads one committed JSON summary. Shared code is limited to atomic downloads, provenance manifests, and raster zonal statistics because those operations are reused across assignments.

**Tech Stack:** Python 3.12; standard-library `unittest`; NumPy 2.5.2; pandas 3.0.5; GeoPandas 1.1.4; Pyogrio 0.11.1; Shapely 2.1.2; PyProj 3.7.2; Rasterio 1.5.1; Matplotlib 3.11.1; Jupyter 1.1.1; nbconvert 7.17.1; Requests 2.34.2; static HTML/CSS and minimal browser JavaScript; GitHub CLI and GitHub Pages.

## Global Constraints

- Study area: Story County, Iowa; Census county FIPS `19169`; SSURGO area symbol `IA169`.
- Field sample: exactly 25 ACPF 2019 `isAG=1` polygons, one per 5 × 5 EPSG:5070 grid cell, centroid inside county, at least 95% area inside county, nearest centroid to cell center, `FBndID` tie-breaker.
- Crop years: USDA NASS CDL 2020, 2021, 2022, and 2023 county GeoTIFFs.
- Sentinel-2 window: `2023-06-01T00:00:00Z/2023-08-31T23:59:59Z`, Element 84 Earth Search collection `sentinel-2-l2a`, first deterministically sorted scene with at least 70% valid SCL pixels over selected fields.
- Weather period: `1991-01-01` through `2023-12-31`; climatology baseline `1991-01-01` through `2020-12-31`; parameters `T2M` and `PRECTOTCORR`.
- Soil snapshot: Web Soil Survey `wss_SSA_IA169_[2025-09-09].zip`; results are screening indicators, not operational farm recommendations.
- Spatial rules: EPSG:4326 for committed web GeoJSON, EPSG:5070 for U.S. area/distance/overlay, native raster CRS for pixel work, nearest-neighbor for categorical raster resampling.
- No synthetic boundaries, crop labels, imagery, NDVI, weather, or soil values. In-memory toy arrays/geometries are allowed only in tests.
- Raw archives, COG windows, county rasters, extracted SSURGO, caches, credentials, and private course material stay gitignored.
- Every nontrivial implementation begins with a failing `unittest` or repository contract check, then the smallest passing implementation.
- Each assignment branch is reviewed independently by DeepSeek V4 Pro and GLM 5.2 before its pull request is merged.
- DeepSeek and GLM receive only tracked public repository files and diffs; never pass `.env`, OAuth files, GitHub tokens, private archives, Classroom exports, or assignment source documents.
- Use merge commits for pull requests so the nine sequential branch/PR boundaries remain visible.
- Use `GH_TOKEN` only in the environment of the individual `gh` or authenticated `git` command. Do not change global GitHub authentication.
- Tracked files must be below 10 MiB each unless a reviewed assignment artifact proves that limit impossible.
- Desktop VS Code screenshots remain a user action; Bellserver evidence must not claim desktop actions it cannot perform.

## Canonical Sources

| Source | Exact acquisition contract |
|---|---|
| Story County | `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query`, `where=GEOID='19169'`, GeoJSON, EPSG:4326 |
| ACPF Iowa fields | `https://ndownloader.figshare.com/files/44528942`, expected SHA-256 `ef9e42cf4456da0c05b68db25a5f8fc02ac11d2ecd9d75fbe4ef741ebe56118f`, layer `IowaFieldBoundaries2019.shp` |
| CDL rasters | `https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile?year={year}&fips=19169`, then download returned URL |
| CDL labels | `https://www.nass.usda.gov/Research_and_Science/Cropland/metadata/metadata_ia23.htm`, parse the official code/name domain |
| Sentinel-2 | `https://earth-search.aws.element84.com/v1/search`, collection `sentinel-2-l2a`, assets `red`, `nir`, and `scl` |
| NASA POWER | `https://power.larc.nasa.gov/api/temporal/daily/point`, community `AG`, format `JSON` |
| SSURGO | `https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/wss_SSA_IA169_%5B2025-09-09%5D.zip` |

## Canonical Output Contracts

| File | Required contract |
|---|---|
| `fields_EPSG4326.geojson` | 25 Polygon/MultiPolygon features; EPSG:4326; unique `field_id`; properties `field_id`, `source_id`, `grid_row`, `grid_col`, `area_ha`, `inside_fraction` |
| `cdl_EPSG4326.csv` | 100 rows sorted by `field_id,year`; columns `field_id,year,cdl_code,cdl_name,majority_fraction,coverage_fraction,valid_pixels,total_pixels`; nullable crop fields only when coverage `< 0.70` |
| `fields_with_crops.geojson` | 25 features; field properties plus `crop_{year}_code`, `crop_{year}_name`, `crop_{year}_fraction`, `crop_{year}_coverage` for 2020–2023 |
| `field_summary.csv` | one row; `field_count,total_area_ha,mean_area_ha,median_area_ha,crop_record_count,missing_crop_record_count,duplicate_field_id_count` |
| `soil_map_units.geojson` | EPSG:4326 soil polygons intersecting selected fields; `mukey,musym,muname` |
| `field_soil_overlap.csv` | one row per field/mapunit intersection; `field_id,mukey,overlap_area_ha,field_fraction` |
| `field_ndvi.csv` | 25 rows; `field_id,mean_ndvi,median_ndvi,valid_pixel_count,total_pixel_count,coverage_fraction` |
| `weather_daily.csv` | 12,053 dates; `date,t2m_c,precip_mm,t2m_7d_c,day_of_year,baseline_t2m_c,t2m_anomaly_c` |
| `integrated_fields.geojson` | 25 features; required properties `field_id,crop_2023_name,dominant_soil,mean_ndvi,ndvi_coverage_fraction` |
| `soil_health_by_field.csv` | 25 rows; `field_id,organic_matter_pct,ph_h2o,cec_cmol_kg,erosion_k_factor,carbon_storage_mg_c_ha,soil_coverage_fraction,om_coverage_fraction,ph_coverage_fraction,cec_coverage_fraction,erosion_coverage_fraction,carbon_coverage_fraction` |
| `docs/data/dashboard.json` | scalar KPI values plus source dates/units; generated from committed assignment summaries, never hand-edited |

Every `data/provenance/*.json` manifest contains:

```json
{
  "dataset": "stable machine name",
  "source_organization": "publisher",
  "source_name": "dataset title",
  "source_urls": ["public URL without credentials"],
  "retrieved_utc": "ISO-8601 UTC timestamp",
  "source_version": "release, scene, year, or snapshot",
  "sha256": {"local-cache-file": "hex digest"},
  "source_crs": "declared CRS",
  "output_crs": "declared CRS",
  "producer": "script path",
  "counts": {},
  "license_note": "public-domain or attribution statement"
}
```

## Review and Merge Protocol

For every feature branch:

1. Run the assignment's focused tests and the complete `python -m unittest discover -s tests -v`.
2. Execute each new notebook from a clean kernel:

   ```bash
   .venv/bin/jupyter nbconvert --execute --to notebook --inplace \
     --ExecutePreprocessor.cwd=. \
     --ExecutePreprocessor.timeout=1800 \
     notebooks/<assignment-notebook>.ipynb
   ```

3. Run `git diff --check`, the repository privacy scan, and `git status --short`.
4. Send the tracked diff to a DeepSeek V4 Pro subagent for requirements/correctness review.
5. Run a read-only GLM review through Hermes:

   ```bash
   hermes --provider zai --model glm-5.2 --reasoning max \
     --ignore-rules -t '' -z "<branch-specific public diff review prompt>"
   ```

6. Verify each finding against the files/tests, fix substantiated issues test-first, and rerun checks.
7. Push the feature branch, open a pull request with test/provenance evidence, and merge with:

   ```bash
   GH_TOKEN="$GITHUB_TOKEN" gh pr merge --merge --delete-branch
   ```

8. Pull `main` before creating the next branch.

---

### Task 1: Commit the Approved Plan and Publish the Baseline Repository

**Files:**
- Modify: `docs/superpowers/specs/2026-08-13-agricultural-data-analytics-course-recreation-design.md`
- Create: `docs/superpowers/plans/2026-08-13-agricultural-data-analytics-course-recreation.md`

**Interfaces:**
- Consumes: approved design commit `67e635e`
- Produces: public `main` containing only the design and implementation plan; remote `origin`

- [ ] **Step 1: Validate the documents**

Run:

```bash
git diff --check
python3 - <<'PY'
import re
from pathlib import Path

text = "\n".join(
    path.read_text(errors="replace")
    for path in Path("docs/superpowers").rglob("*.md")
)
red_flags = ("T" + "BD", "TO" + "DO", "FIX" + "ME", "PLACE" + "HOLDER")
assert not any(flag in text for flag in red_flags)
secret_patterns = (
    re.compile(r"GOCSPX-[A-Za-z0-9_-]{10,}"),
    re.compile(r"client_secret[\"']?\s*[:=]\s*[\"'][^\"']{8,}"),
    re.compile(r"refresh_token[\"']?\s*[:=]\s*[\"'][^\"']{8,}"),
    re.compile(r"access_token[\"']?\s*[:=]\s*[\"'][^\"']{8,}"),
)
assert not any(pattern.search(text) for pattern in secret_patterns)
PY
```

Expected: both commands exit `0`; the search prints no matches.

- [ ] **Step 2: Commit the amendment and plan**

```bash
git add docs/superpowers/specs/2026-08-13-agricultural-data-analytics-course-recreation-design.md \
        docs/superpowers/plans/2026-08-13-agricultural-data-analytics-course-recreation.md
git commit -m "docs: plan course recreation implementation"
```

- [ ] **Step 3: Create the public GitHub repository without persisting the token**

Load only `GITHUB_TOKEN` from `/home/bell/.hermes/.env` into the current process, verify the account is `bayhnf`, then run:

```bash
GITHUB_TOKEN="$(
  python3 - <<'PY'
import shlex
from pathlib import Path

for raw in Path("/home/bell/.hermes/.env").read_text().splitlines():
    if raw.startswith("GITHUB_TOKEN="):
        value = raw.split("=", 1)[1].strip()
        print(shlex.split(value)[0] if value else "")
        break
PY
)"
test -n "$GITHUB_TOKEN"
GH_TOKEN="$GITHUB_TOKEN" gh api user --jq .login
GH_TOKEN="$GITHUB_TOKEN" gh repo create bayhnf/Agricultural-Data-Analytics \
  --public --source=. --remote=origin --push
```

Expected: account output `bayhnf`; repository creation and initial push succeed.

- [ ] **Step 4: Verify remote state**

```bash
GH_TOKEN="$GITHUB_TOKEN" gh repo view bayhnf/Agricultural-Data-Analytics \
  --json nameWithOwner,visibility,defaultBranchRef
git remote -v
git status --short --branch
```

Expected: public repository, default branch `main`, clean worktree.

### Task 2: Assignment 1 — Setup, Mermaid, OpenCode, and Honest Evidence

**Branch:** `feature/assignment-01-setup`

**Files:**
- Create: `.gitignore`
- Create: `.python-version`
- Create: `requirements.txt`
- Create: `README.md`
- Create: `docs/reports/assignment-01-evidence.md`
- Create: `tests/test_assignment_01_repository.py`

**Interfaces:**
- Consumes: Python 3.12 and Node.js already present on Bellserver
- Produces: reproducible environment contract, rendered GitHub Mermaid source, OpenCode version evidence, explicit desktop evidence handoff

- [ ] **Step 1: Create the branch and write the failing repository contract**

```python
# tests/test_assignment_01_repository.py
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class Assignment01RepositoryTest(unittest.TestCase):
    def test_required_setup_files_and_mermaid_exist(self):
        for relative in (
            ".gitignore",
            ".python-version",
            "requirements.txt",
            "README.md",
            "docs/reports/assignment-01-evidence.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("```mermaid", readme)
        self.assertIn("Assignment 1", readme)

    def test_private_paths_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        for pattern in (".env", ".venv/", "data/raw/", "*.zip", "*.tif"):
            self.assertIn(pattern, ignored)
```

Run:

```bash
git switch -c feature/assignment-01-setup
python -m unittest tests.test_assignment_01_repository -v
```

Expected: FAIL because the required files do not exist.

- [ ] **Step 2: Add the minimum environment files**

`.python-version`:

```text
3.12
```

`requirements.txt`:

```text
geopandas==1.1.4
jupyter==1.1.1
matplotlib==3.11.1
nbconvert==7.17.1
numpy==2.5.2
pandas==3.0.5
pyogrio==0.11.1
pyproj==3.7.2
rasterio==1.5.1
requests==2.34.2
shapely==2.1.2
```

`.gitignore` must include:

```text
.env
.env.*
.venv/
__pycache__/
*.py[cod]
.ipynb_checkpoints/
data/raw/
*.zip
*.tif
*.tiff
*.jp2
*.tmp
```

- [ ] **Step 3: Write the README and evidence report**

The README must contain:

- course recreation purpose and Story County scope;
- a Mermaid flowchart from official sources to GitHub Pages;
- exact `uv venv --python 3.12 .venv` and `uv pip install --python .venv/bin/python -r requirements.txt` commands;
- `python -m unittest discover -s tests -v`;
- raw-cache and privacy rules;
- assignment/branch table for all nine feature branches;
- source limitations: ACPF boundaries are edited historical CLU-derived analysis units, POWER is gridded assimilated data, and soil/carbon metrics are screening estimates.

The evidence report must include command output from:

```bash
python3.12 --version
node --version
git --version
opencode --version
```

It must also state:

```text
VS Code desktop evidence cannot be produced on Bellserver. The user must open the cloned
repository in VS Code on Windows and capture that genuine screenshot before submitting
Assignment 1. No screenshot is fabricated in this repository.
```

- [ ] **Step 4: Install and verify OpenCode**

Use the official npm package at the planning-time verified version:

```bash
npm install --global opencode-ai@1.18.18
opencode --version
```

Record only the version and command in the evidence report. Do not configure a provider or copy any provider credential.

- [ ] **Step 5: Create and verify the Python environment**

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m unittest tests.test_assignment_01_repository -v
```

Expected: PASS.

- [ ] **Step 6: Run full verification, review, commit, push, PR, and merge**

```bash
.venv/bin/python -m unittest discover -s tests -v
git diff --check
git add .gitignore .python-version requirements.txt README.md \
        docs/reports/assignment-01-evidence.md tests/test_assignment_01_repository.py
git commit -m "feat: add assignment 1 project setup"
```

DeepSeek prompt scope: Assignment 1 requirements, evidence honesty, dependency minimality, privacy.

GLM prompt scope: README/Mermaid rendering, OpenCode evidence, desktop-user-action wording, branch contract.

PR title: `Assignment 1: project setup and planning evidence`.

### Task 3: Assignment 2A — Public Acquisition, Provenance, and Deterministic Field Selection

**Branch:** `feature/assignment-02-first-data`

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/common.py`
- Create: `scripts/assignment_02.py`
- Create: `tests/test_assignment_02_fields.py`
- Create: `data/provenance/story_county.json`
- Create: `data/provenance/acpf_fields.json`
- Create: `data/processed/assignment-02/fields_EPSG4326.geojson`

**Interfaces:**
- Produces: `download_atomic(url: str, destination: Path, expected_sha256: str | None = None) -> str`
- Produces: `write_manifest(path: Path, manifest: dict) -> None`
- Produces: `select_grid_fields(fields: GeoDataFrame, county: BaseGeometry) -> GeoDataFrame`
- Produces: exactly 25 selected fields consumed by every later assignment

- [ ] **Step 1: Write the failing pure selection tests**

```python
# tests/test_assignment_02_fields.py
import unittest

import geopandas as gpd
from shapely.geometry import box

from scripts.assignment_02 import select_grid_fields


class FieldSelectionTest(unittest.TestCase):
    def test_selects_one_field_per_grid_cell_with_stable_ids(self):
        county = box(0, 0, 50, 50)
        rows = []
        for row in range(5):
            for col in range(5):
                rows.append({
                    "FBndID": f"B-{row}-{col}",
                    "isAG": 1,
                    "geometry": box(col * 10 + 4, row * 10 + 4,
                                    col * 10 + 6, row * 10 + 6),
                })
        fields = gpd.GeoDataFrame(rows, crs=5070)
        selected = select_grid_fields(fields, county)
        self.assertEqual(list(selected["field_id"]),
                         [f"STORY-{number:02d}" for number in range(1, 26)])
        self.assertEqual(len(selected), 25)
        self.assertEqual(selected["source_id"].nunique(), 25)

    def test_rejects_missing_grid_cell(self):
        county = box(0, 0, 50, 50)
        fields = gpd.GeoDataFrame(
            [{"FBndID": "only-one", "isAG": 1, "geometry": box(4, 4, 6, 6)}],
            crs=5070,
        )
        with self.assertRaisesRegex(ValueError, "25 populated grid cells"):
            select_grid_fields(fields, county)
```

Run:

```bash
git switch main
git pull --ff-only
git switch -c feature/assignment-02-first-data
.venv/bin/python -m unittest tests.test_assignment_02_fields -v
```

Expected: FAIL because `scripts.assignment_02` does not exist.

- [ ] **Step 2: Implement atomic download and manifest writing**

```python
# scripts/common.py
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_atomic(url: str, destination: Path,
                    expected_sha256: str | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        if "text/html" in response.headers.get("content-type", ""):
            raise ValueError(f"refusing HTML response from {url}")
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)
    digest = sha256_file(temporary)
    if expected_sha256 and digest != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {url}")
    os.replace(temporary, destination)
    return digest


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
```

- [ ] **Step 3: Implement selection and real acquisition**

`select_grid_fields` must:

1. require CRS and reproject to EPSG:5070;
2. filter `isAG == 1`, nonempty, valid, unique `FBndID`;
3. retain centroid-within-county and `inside_fraction >= 0.95`;
4. build a 5 × 5 grid from county bounds;
5. stable-sort candidates by centroid distance and `FBndID`;
6. assign `STORY-01` through `STORY-25` in row-major grid order;
7. calculate `area_ha` from original selected geometry;
8. export EPSG:4326 GeoJSON sorted by `field_id`.

The command entry point is:

```python
def build_fields(raw_dir: Path, output_dir: Path, provenance_dir: Path) -> None:
    ...


if __name__ == "__main__":
    build_fields(Path("data/raw"), Path("data/processed/assignment-02"),
                 Path("data/provenance"))
```

- [ ] **Step 4: Run the unit test and real-data build**

```bash
.venv/bin/python -m unittest tests.test_assignment_02_fields -v
.venv/bin/python -m scripts.assignment_02
```

Expected: tests PASS; GeoJSON has exactly 25 fields; manifests contain source URLs, checksums, CRS, counts, and public-domain notes.

- [ ] **Step 5: Add the real-output contract**

```python
    def test_committed_field_contract(self):
        path = "data/processed/assignment-02/fields_EPSG4326.geojson"
        fields = gpd.read_file(path)
        self.assertEqual(len(fields), 25)
        self.assertEqual(fields.crs.to_epsg(), 4326)
        self.assertEqual(fields["field_id"].nunique(), 25)
        self.assertTrue((fields["inside_fraction"] >= 0.95).all())
        self.assertTrue((fields["area_ha"] > 0).all())
```

Run the focused test again and commit:

```bash
.venv/bin/python -m unittest tests.test_assignment_02_fields -v
git add scripts data/provenance/story_county.json data/provenance/acpf_fields.json \
        data/processed/assignment-02/fields_EPSG4326.geojson \
        tests/test_assignment_02_fields.py
git commit -m "feat: select Story County field sample"
```

### Task 4: Assignment 2B — CDL Zonal Majority, Joined Fields, Summary, and Map

**Branch:** continue `feature/assignment-02-first-data`

**Files:**
- Create: `scripts/zonal.py`
- Modify: `scripts/assignment_02.py`
- Modify: `tests/test_assignment_02_fields.py`
- Create: `data/provenance/cdl_2020_2023.json`
- Create: `data/processed/assignment-02/cdl_EPSG4326.csv`
- Create: `data/processed/assignment-02/fields_with_crops.geojson`
- Create: `data/processed/assignment-02/field_summary.csv`
- Create: `data/processed/assignment-02/my_fields_map.html`

**Interfaces:**
- Produces: `categorical_summary(values: ndarray, valid_mask: ndarray, minimum_coverage: float = 0.70) -> dict`
- Produces: `continuous_summary(values: ndarray, valid_mask: ndarray) -> dict`, reused by Assignment 5/7
- Consumes: 25-field GeoJSON from Task 3

- [ ] **Step 1: Write the failing categorical-statistics tests**

```python
from scripts.zonal import categorical_summary


class CategoricalSummaryTest(unittest.TestCase):
    def test_returns_stable_majority_and_coverage(self):
        values = np.array([[1, 1], [5, 0]], dtype="uint8")
        result = categorical_summary(values, values != 0, minimum_coverage=0.70)
        self.assertEqual(result["value"], 1)
        self.assertEqual(result["valid_pixels"], 3)
        self.assertEqual(result["total_pixels"], 4)
        self.assertAlmostEqual(result["coverage_fraction"], 0.75)
        self.assertAlmostEqual(result["majority_fraction"], 2 / 3)

    def test_nulls_class_when_coverage_is_too_low(self):
        values = np.array([[1, 0], [0, 0]], dtype="uint8")
        result = categorical_summary(values, values != 0, minimum_coverage=0.70)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["majority_fraction"])
```

Run:

```bash
.venv/bin/python -m unittest tests.test_assignment_02_fields.CategoricalSummaryTest -v
```

Expected: FAIL because `scripts.zonal` does not exist.

- [ ] **Step 2: Implement the two small zonal reducers**

`categorical_summary` must use `numpy.unique(..., return_counts=True)`, choose the lowest code on a count tie, and report coverage before applying the 0.70 threshold.

`continuous_summary` must return:

```python
{
    "mean": float | None,
    "median": float | None,
    "valid_pixels": int,
    "total_pixels": int,
    "coverage_fraction": float,
}
```

It must ignore non-finite values and return null mean/median when no valid pixels exist.

- [ ] **Step 3: Implement CDL acquisition and per-field/year extraction**

For each year 2020–2023:

- call `GetCDLFile` and parse `<returnURL>`;
- download the returned county GeoTIFF atomically;
- checksum it and record raster CRS, dimensions, and code counts;
- mask each field in the raster CRS with `rasterio.mask.mask(..., crop=True)`;
- treat code `0` as no-data;
- apply `categorical_summary(..., minimum_coverage=0.70)`;
- map codes to names parsed from the official Iowa 2023 metadata domain;
- stable-sort the 100 output rows.

Generate the standalone Leaflet map with a small HTML string and CDN links; embed only the 25-field GeoJSON, not any private or raw source.

- [ ] **Step 4: Add exact output-contract tests**

```python
    def test_assignment_02_products(self):
        crops = pd.read_csv("data/processed/assignment-02/cdl_EPSG4326.csv")
        self.assertEqual(list(crops.columns), [
            "field_id", "year", "cdl_code", "cdl_name",
            "majority_fraction", "coverage_fraction",
            "valid_pixels", "total_pixels",
        ])
        self.assertEqual(len(crops), 100)
        self.assertEqual(set(crops["year"]), {2020, 2021, 2022, 2023})
        self.assertFalse(crops.duplicated(["field_id", "year"]).any())

        joined = gpd.read_file(
            "data/processed/assignment-02/fields_with_crops.geojson"
        )
        self.assertEqual(len(joined), 25)
        self.assertEqual(joined["field_id"].nunique(), 25)
```

- [ ] **Step 5: Build, verify, review, and merge Assignment 2**

```bash
.venv/bin/python -m scripts.assignment_02
.venv/bin/python -m unittest tests.test_assignment_02_fields -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
git add scripts/zonal.py scripts/assignment_02.py tests/test_assignment_02_fields.py \
        data/provenance/cdl_2020_2023.json data/processed/assignment-02
git commit -m "feat: integrate assignment 2 crop history"
```

DeepSeek prompt scope: selection determinism, raster masking correctness, CDL schema and provenance.

GLM prompt scope: exact Assignment 2 filenames, 100-row crop contract, interactive map, no synthetic data.

PR title: `Assignment 2: integrate real field and crop data`.

### Task 5: Assignment 3 — Executable EDA Notebook and Three Real Visualizations

**Branch:** `feature/assignment-03-eda`

**Files:**
- Create: `notebooks/03_field_eda.ipynb`
- Create: `tests/test_assignment_03_eda.py`
- Create: `docs/assets/field_area_distribution.png`
- Create: `docs/assets/crop_mix_2023.png`
- Create: `docs/assets/crop_rotation_patterns.png`

**Interfaces:**
- Consumes: Assignment 2 GeoJSON and crop CSV
- Produces: three figures; two or more are dashboard-ready

- [ ] **Step 1: Write the failing notebook/output contract**

```python
# tests/test_assignment_03_eda.py
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class Assignment03Test(unittest.TestCase):
    def test_notebook_and_three_figures_exist(self):
        notebook = ROOT / "notebooks/03_field_eda.ipynb"
        self.assertTrue(notebook.is_file())
        document = json.loads(notebook.read_text())
        joined = "\n".join(
            "".join(cell.get("source", [])) for cell in document["cells"]
        )
        for phrase in ("area_ha", "crop_2023_name", "rotation"):
            self.assertIn(phrase, joined)
        for name in (
            "field_area_distribution.png",
            "crop_mix_2023.png",
            "crop_rotation_patterns.png",
        ):
            self.assertGreater((ROOT / "docs/assets" / name).stat().st_size, 1000)
```

Run and expect FAIL.

- [ ] **Step 2: Create the notebook with real analysis**

Notebook sections:

1. purpose, sources, and ACPF temporal limitation;
2. load Assignment 2 products and assert 25 unique fields;
3. missingness and descriptive statistics;
4. field-area histogram;
5. 2023 crop-count bar chart;
6. 2020–2023 crop-sequence frequency chart;
7. observations tied to calculated counts and medians.

Use fixed Matplotlib colors, `tight_layout()`, 160 DPI, descriptive titles, units, and source captions.

- [ ] **Step 3: Execute and verify**

```bash
.venv/bin/jupyter nbconvert --execute --to notebook --inplace \
  --ExecutePreprocessor.cwd=. --ExecutePreprocessor.timeout=600 \
  notebooks/03_field_eda.ipynb
.venv/bin/python -m unittest tests.test_assignment_03_eda -v
.venv/bin/python -m unittest discover -s tests -v
```

- [ ] **Step 4: Review and merge**

Commit:

```bash
git add notebooks/03_field_eda.ipynb docs/assets tests/test_assignment_03_eda.py
git commit -m "feat: add assignment 3 field EDA"
```

DeepSeek prompt scope: analysis validity and claims supported by real outputs.

GLM prompt scope: three-visualization requirement, notebook execution, figure polish.

PR title: `Assignment 3: exploratory field analysis`.

### Task 6: Assignment 4 — SSURGO Field/Soil Mapping

**Branch:** `feature/assignment-04-mapping`

**Files:**
- Create: `scripts/assignment_04.py`
- Create: `tests/test_assignment_04_mapping.py`
- Create: `data/provenance/ssurgo_ia169.json`
- Create: `data/processed/assignment-04/soil_map_units.geojson`
- Create: `data/processed/assignment-04/field_soil_overlap.csv`
- Create: `notebooks/04_field_mapping.ipynb`
- Create: `docs/assets/field_spatial_map.png`

**Interfaces:**
- Produces: field/mapunit overlap table used by Assignments 7 and 8
- Consumes: selected fields and fixed SSURGO snapshot

- [ ] **Step 1: Write the failing area-overlay test**

```python
# tests/test_assignment_04_mapping.py
import unittest

import geopandas as gpd
from shapely.geometry import box

from scripts.assignment_04 import calculate_field_soil_overlap


class SoilOverlapTest(unittest.TestCase):
    def test_reports_area_fraction_per_field(self):
        fields = gpd.GeoDataFrame(
            [{"field_id": "STORY-01", "geometry": box(0, 0, 10, 10)}],
            crs=5070,
        )
        soils = gpd.GeoDataFrame([
            {"mukey": "A", "geometry": box(0, 0, 5, 10)},
            {"mukey": "B", "geometry": box(5, 0, 10, 10)},
        ], crs=5070)
        result = calculate_field_soil_overlap(fields, soils)
        self.assertEqual(list(result["mukey"]), ["A", "B"])
        self.assertAlmostEqual(result["field_fraction"].sum(), 1.0)
```

Run and expect FAIL.

- [ ] **Step 2: Implement fixed-snapshot acquisition and overlay**

`assignment_04.py` must:

- atomically download and checksum the 2025-09-09 `IA169` zip;
- reject corrupt archives with `ZipFile.testzip()`;
- read `IA169/spatial/soilmu_a_ia169.shp`;
- read `mapunit.txt` using column positions derived from `mstabcol.txt`, not guessed indexes;
- reproject fields and mapunits to EPSG:5070;
- overlay only polygons intersecting selected fields;
- calculate overlap area and fraction;
- export mapunits in EPSG:4326 and stable-sort overlap rows.

- [ ] **Step 3: Create and execute the mapping notebook**

Notebook must plot selected field outlines over soil mapunit polygons, explain CRS alignment, report soil coverage, and identify the most common mapunit by field-overlap area.

```bash
.venv/bin/python -m scripts.assignment_04
.venv/bin/jupyter nbconvert --execute --to notebook --inplace \
  --ExecutePreprocessor.cwd=. --ExecutePreprocessor.timeout=900 \
  notebooks/04_field_mapping.ipynb
```

- [ ] **Step 4: Add committed-output checks**

Test exactly 25 field IDs in overlap output, unique `mukey` values in the soil GeoJSON, EPSG:4326 output CRS, fractions in `[0,1]`, and `field_spatial_map.png` above 1,000 bytes.

- [ ] **Step 5: Verify, review, and merge**

Commit message: `feat: add assignment 4 field soil mapping`.

DeepSeek prompt scope: SSURGO snapshot parsing, CRS, overlay-area correctness.

GLM prompt scope: map requirement, interpretation, output path, source limitation.

PR title: `Assignment 4: map fields and SSURGO soils`.

### Task 7: Assignment 5 — Real Sentinel-2 Imagery, Cloud Mask, and NDVI

**Branch:** `feature/assignment-05-ndvi`

**Files:**
- Create: `scripts/assignment_05.py`
- Create: `tests/test_assignment_05_ndvi.py`
- Create: `data/provenance/sentinel_2023.json`
- Create: `data/processed/assignment-05/scene.json`
- Create: `data/processed/assignment-05/field_ndvi.csv`
- Create: `notebooks/05_satellite_ndvi.ipynb`
- Create: `docs/assets/sentinel_red_band.png`
- Create: `docs/assets/ndvi_map.png`
- Create: `docs/reports/assignment-05-walkthrough.md`

**Interfaces:**
- Produces: `valid_scl_mask(scl: ndarray) -> ndarray[bool]`
- Produces: `calculate_ndvi(red: ndarray, nir: ndarray, scale: float, offset: float, valid_mask: ndarray) -> ndarray`
- Produces: field NDVI consumed by Assignment 7 and dashboard

- [ ] **Step 1: Write failing cloud-mask and reflectance tests**

```python
# tests/test_assignment_05_ndvi.py
import unittest

import numpy as np

from scripts.assignment_05 import calculate_ndvi, valid_scl_mask


class NdviTest(unittest.TestCase):
    def test_scl_excludes_invalid_classes(self):
        scl = np.arange(12, dtype="uint8")
        self.assertEqual(
            valid_scl_mask(scl).tolist(),
            [False, False, False, False, True, True,
             True, True, False, False, False, False],
        )

    def test_applies_stac_scale_and_offset_before_ndvi(self):
        red = np.array([[2000]], dtype="uint16")
        nir = np.array([[5000]], dtype="uint16")
        result = calculate_ndvi(
            red, nir, scale=0.0001, offset=-0.1,
            valid_mask=np.array([[True]]),
        )
        self.assertAlmostEqual(float(result[0, 0]), 0.6)
```

Run and expect FAIL.

- [ ] **Step 2: Implement deterministic scene selection**

Query Earth Search, then client-side sort by:

```python
(
    feature["properties"].get("eo:cloud_cover", float("inf")),
    feature["properties"]["datetime"],
    feature["id"],
)
```

For each candidate:

- window-read `scl` over the selected-field bounds;
- rasterize the union of selected fields on the SCL grid;
- calculate valid fraction using valid classes `{4,5,6,7}`;
- select the first candidate at or above `0.70`.

Record every rejected candidate's scene ID and valid fraction in `scene.json`.

- [ ] **Step 3: Implement reflectance and NDVI processing**

- window-read `red` and `nir` assets;
- apply each asset's STAC `scale` and `offset`;
- reproject SCL to the red-band 10 m grid with `Resampling.nearest`;
- mask raw band nodata, invalid SCL, outside-field pixels, and zero denominator;
- constrain finite NDVI output to `[-1,1]`;
- calculate per-field summaries with `continuous_summary`;
- cache raw windows only under `data/raw/sentinel/`;
- save the two real figures and the 25-row CSV.

- [ ] **Step 4: Write the notebook and walkthrough**

The notebook must show:

- selected scene ID/date and study-area valid fraction;
- a real red-band image;
- the cloud-masked NDVI image;
- field-level NDVI distribution;
- interpretation and limitations.

The walkthrough must state the excluded SCL classes, 20 m→10 m nearest-neighbor rule, reflectance scale/offset, selected-scene threshold, and Copernicus attribution.

- [ ] **Step 5: Execute, verify, review, and merge**

```bash
.venv/bin/python -m scripts.assignment_05
.venv/bin/jupyter nbconvert --execute --to notebook --inplace \
  --ExecutePreprocessor.cwd=. --ExecutePreprocessor.timeout=1800 \
  notebooks/05_satellite_ndvi.ipynb
.venv/bin/python -m unittest tests.test_assignment_05_ndvi -v
.venv/bin/python -m unittest discover -s tests -v
```

Commit message: `feat: add assignment 5 Sentinel NDVI analysis`.

DeepSeek prompt scope: STAC selection, scale/offset, SCL resampling, raster masks, field summaries.

GLM prompt scope: teacher's real-imagery requirement, walkthrough completeness, required figures and attribution.

PR title: `Assignment 5: analyze real Sentinel-2 NDVI`.

### Task 8: Assignment 6 — NASA POWER Weather Trends and Anomalies

**Branch:** `feature/assignment-06-weather`

**Files:**
- Create: `scripts/assignment_06.py`
- Create: `tests/test_assignment_06_weather.py`
- Create: `data/provenance/nasa_power_1991_2023.json`
- Create: `data/processed/assignment-06/weather_daily.csv`
- Create: `data/processed/assignment-06/weather_summary.json`
- Create: `notebooks/06_weather_analysis.ipynb`
- Create: `docs/assets/weather_trends.png`

**Interfaces:**
- Produces: `parse_power_daily(payload: dict) -> DataFrame`
- Produces: daily temperature/precipitation and 2023 anomaly data

- [ ] **Step 1: Write failing parser/anomaly tests**

```python
# tests/test_assignment_06_weather.py
import unittest

from scripts.assignment_06 import parse_power_daily


class WeatherTest(unittest.TestCase):
    def test_parses_dates_and_converts_fill_values_to_null(self):
        payload = {"properties": {"parameter": {
            "T2M": {"20230101": 1.0, "20230102": -999.0},
            "PRECTOTCORR": {"20230101": 2.5, "20230102": 0.0},
        }}}
        frame = parse_power_daily(payload)
        self.assertEqual(frame.loc[0, "date"].isoformat(), "2023-01-01")
        self.assertTrue(frame.loc[1, "t2m_c"] != frame.loc[1, "t2m_c"])
        self.assertEqual(frame.loc[0, "precip_mm"], 2.5)
```

Run and expect FAIL.

- [ ] **Step 2: Implement one bounded API request and calculations**

Use the EPSG:4326 centroid of the union of selected fields. Request the full period in one call. Validate:

- exactly 12,053 date keys;
- both parameters exist;
- dates are unique and continuous;
- `-999` becomes null;
- precipitation below zero is rejected.

Calculate a centered 7-day temperature rolling mean. Build day-of-year baseline means from 1991–2020, handling February 29 as its own day, and calculate 2023 daily temperature anomalies.

- [ ] **Step 3: Produce notebook and figure**

The figure contains temperature with 7-day average, daily precipitation, and 2023 temperature anomaly. The notebook calls the source “NASA POWER gridded assimilated estimates,” not observations.

- [ ] **Step 4: Execute, verify, review, and merge**

```bash
.venv/bin/python -m scripts.assignment_06
.venv/bin/jupyter nbconvert --execute --to notebook --inplace \
  --ExecutePreprocessor.cwd=. --ExecutePreprocessor.timeout=900 \
  notebooks/06_weather_analysis.ipynb
.venv/bin/python -m unittest tests.test_assignment_06_weather -v
.venv/bin/python -m unittest discover -s tests -v
```

Commit message: `feat: add assignment 6 weather analysis`.

DeepSeek prompt scope: API completeness, fill handling, baseline/anomaly arithmetic.

GLM prompt scope: time-series, rolling-average, anomaly, terminology and figure requirement.

PR title: `Assignment 6: analyze NASA POWER weather`.

### Task 9: Assignment 7 — Spatial Integration and Field-Level NDVI

**Branch:** `feature/assignment-07-zonal-stats`

**Files:**
- Create: `scripts/assignment_07.py`
- Create: `tests/test_assignment_07_integration.py`
- Create: `data/processed/assignment-07/integrated_field_summary.csv`
- Create: `data/processed/assignment-07/integrated_fields.geojson`
- Create: `notebooks/07_spatial_integration.ipynb`
- Create: `docs/assets/integrated_spatial_analysis.png`

**Interfaces:**
- Consumes: Assignment 2 crops, Assignment 4 field/soil overlaps, Assignment 5 NDVI
- Produces: one 25-field integrated dataset

- [ ] **Step 1: Write the failing one-to-one integration test**

```python
# tests/test_assignment_07_integration.py
import unittest

import pandas as pd

from scripts.assignment_07 import integrate_fields


class IntegrationTest(unittest.TestCase):
    def test_preserves_all_fields_and_null_ndvi(self):
        fields = pd.DataFrame({"field_id": ["A", "B"]})
        crops = pd.DataFrame({
            "field_id": ["A", "B"],
            "crop_2023_name": ["Corn", "Soybeans"],
        })
        soils = pd.DataFrame({
            "field_id": ["A", "B"],
            "dominant_soil": ["108", "108B"],
        })
        ndvi = pd.DataFrame({
            "field_id": ["A", "B"],
            "mean_ndvi": [0.7, None],
            "coverage_fraction": [0.9, 0.2],
        })
        result = integrate_fields(fields, crops, soils, ndvi)
        self.assertEqual(list(result["field_id"]), ["A", "B"])
        self.assertTrue(pd.isna(result.loc[1, "mean_ndvi"]))
```

Run and expect FAIL.

- [ ] **Step 2: Implement strict joins and dominant soil**

- derive dominant soil by maximum `overlap_area_ha`, `mukey` tie-breaker;
- select 2023 crop columns;
- validate every input key is unique at merge time;
- merge with `validate="one_to_one"`;
- preserve null `mean_ndvi` when coverage is insufficient;
- export CSV and EPSG:4326 GeoJSON sorted by `field_id`.

- [ ] **Step 3: Create the integration notebook and figure**

Notebook must explain the shared zonal-statistics method, report valid-pixel coverage, map fields by `mean_ndvi`, and compare NDVI by 2023 crop and dominant soil without implying causation.

- [ ] **Step 4: Execute, verify, review, and merge**

Commit message: `feat: add assignment 7 spatial integration`.

DeepSeek prompt scope: one-to-one joins, null preservation, dominant-soil calculation.

GLM prompt scope: fields+soil+NDVI requirement, `mean_ndvi` evidence, integrated figure.

PR title: `Assignment 7: integrate crop soil and NDVI`.

### Task 10: Assignment 8 — Soil Health and Carbon Screening Metrics

**Branch:** `feature/assignment-08-soil-health`

**Files:**
- Create: `scripts/assignment_08.py`
- Create: `tests/test_assignment_08_soil.py`
- Create: `data/processed/assignment-08/soil_health_by_field.csv`
- Create: `data/processed/assignment-08/soil_health_summary.json`
- Create: `notebooks/08_soil_sustainability.ipynb`
- Create: `docs/assets/soil_health_metrics.png`

**Interfaces:**
- Produces: `horizon_overlap_cm(top_cm: float, bottom_cm: float, limit_cm: float = 30) -> float`
- Produces: `aggregate_soil_metrics(...) -> DataFrame`
- Consumes: SSURGO `component`, `chorizon`, and Assignment 4 field/mapunit overlaps

- [ ] **Step 1: Write failing depth, pH, and carbon tests**

```python
# tests/test_assignment_08_soil.py
import math
import unittest

from scripts.assignment_08 import (
    carbon_stock_mg_ha,
    horizon_overlap_cm,
    weighted_ph,
)


class SoilMetricTest(unittest.TestCase):
    def test_clips_horizon_to_top_30_cm(self):
        self.assertEqual(horizon_overlap_cm(10, 40), 20)
        self.assertEqual(horizon_overlap_cm(35, 60), 0)

    def test_carbon_stock_uses_om_to_soc_conversion(self):
        # 3.448% OM -> 2% SOC; 1.3 g/cm3; 30 cm -> 78 Mg C/ha
        self.assertAlmostEqual(carbon_stock_mg_ha(3.448, 1.3, 30), 78.0)

    def test_weighted_ph_averages_hydrogen_concentration(self):
        result = weighted_ph([(6.0, 1.0), (7.0, 1.0)])
        self.assertAlmostEqual(result, -math.log10((1e-6 + 1e-7) / 2))
```

Run and expect FAIL.

- [ ] **Step 2: Parse only required SSURGO columns**

Use `mstabcol.txt` to locate:

- `component`: `mukey`, `cokey`, `comppct_r`, `compname`;
- `chorizon`: `cokey`, `hzdept_r`, `hzdepb_r`, `om_r`, `ph1to1h2o_r`, `cec7_r`, `dbthirdbar_r`, `kwfact`;
- `mapunit`: `mukey`, `musym`, `muname`.

Do not load unrelated SSURGO tables.

- [ ] **Step 3: Implement explicit weighting**

For each metric:

1. clip horizons to 0–30 cm and weight by overlap thickness;
2. aggregate horizons to component;
3. weight components by `comppct_r`;
4. weight mapunits by field intersection area;
5. report a separate coverage fraction for each metric.

Formulas:

```python
soc_percent = organic_matter_percent / 1.724
carbon_storage_mg_c_ha = bulk_density_g_cm3 * thickness_cm * soc_percent
```

Use concentration-space weighting for pH. Use `kwfact` as the erosion-risk proxy. Do not impute missing soil properties.

- [ ] **Step 4: Create notebook and figure**

Notebook sections: OM, pH, CEC, erosion K-factor, carbon stock screening estimate, coverage/missingness, limitations. The figure must display all five metrics with units.

- [ ] **Step 5: Execute, verify, review, and merge**

Commit message: `feat: add assignment 8 soil health analysis`.

DeepSeek prompt scope: SSURGO table joins, depth/component/area weighting, units, carbon arithmetic.

GLM prompt scope: all five rubric metrics, coverage, interpretation, screening-language honesty.

PR title: `Assignment 8: assess soil health and sustainability`.

### Task 11: Final Project — Accessible Static Dashboard

**Branch:** `feature/final-dashboard`

**Files:**
- Create: `scripts/build_dashboard.py`
- Create: `scripts/verify_repository.py`
- Create: `tests/test_dashboard.py`
- Create: `docs/index.html`
- Create: `docs/styles.css`
- Create: `docs/data/dashboard.json`

**Interfaces:**
- Consumes: committed Assignment 2–8 summaries and figures
- Produces: GitHub Pages document rooted at `docs/index.html`

- [ ] **Step 1: Write the failing dashboard contract**

```python
# tests/test_dashboard.py
import json
import pathlib
import unittest
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).parents[1]


class ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "img":
            self.images.append(attributes)
        if tag == "h1":
            self.h1_count += 1


class DashboardTest(unittest.TestCase):
    def test_dashboard_sections_assets_and_accessibility(self):
        html = (ROOT / "docs/index.html").read_text()
        for section in (
            'id="fields"', 'id="vegetation"', 'id="weather"',
            'id="integration"', 'id="soil"', 'id="methods"',
            'id="limitations"', 'id="provenance"',
        ):
            self.assertIn(section, html)
        parser = ImageParser()
        parser.feed(html)
        self.assertEqual(parser.h1_count, 1)
        self.assertGreaterEqual(len(parser.images), 5)
        self.assertTrue(all(image.get("alt", "").strip()
                            for image in parser.images))
        for image in parser.images:
            self.assertTrue((ROOT / "docs" / image["src"]).is_file())

    def test_dashboard_data_is_generated(self):
        data = json.loads((ROOT / "docs/data/dashboard.json").read_text())
        self.assertEqual(data["field_count"], 25)
        self.assertIn("scene_date", data)
        self.assertIn("t2m_anomaly_2023_c", data)
```

Run and expect FAIL.

- [ ] **Step 2: Implement the data builder**

`build_dashboard.py` reads committed CSV/JSON products and writes sorted JSON containing:

```text
field_count
total_area_ha
dominant_crop_2023
mean_ndvi
ndvi_coverage_pct
scene_date
t2m_anomaly_2023_c
precip_2023_mm
mean_organic_matter_pct
mean_ph
mean_cec_cmol_kg
mean_carbon_storage_mg_c_ha
```

Reject missing inputs and non-finite KPI values. `field_count` must equal 25.

- [ ] **Step 3: Build the static page**

Use semantic HTML with one `<h1>`, skip link, keyboard-focus styles, responsive CSS grid, high-contrast palette, and sections required by the design. Include at least:

- `field_area_distribution.png`;
- `crop_mix_2023.png`;
- `field_spatial_map.png`;
- `ndvi_map.png`;
- `weather_trends.png`;
- `integrated_spatial_analysis.png`;
- `soil_health_metrics.png`.

Include “Contains modified Copernicus Sentinel data 2023” and source/limitation text. KPI values are loaded from `data/dashboard.json`; no duplicated hardcoded values.

- [ ] **Step 4: Implement the privacy and file-size verifier**

`verify_repository.py` must:

- inspect only `git ls-files`;
- reject filenames containing `.env`, Classroom archive names, OAuth/token names, or private source zip names;
- reject token patterns `ghp_`, `github_pat_`, `GOCSPX-`, `refresh_token`, and `client_secret`;
- reject tracked files above 10 MiB;
- reject missing HTML image/data references;
- print counts and exit nonzero on any finding.

- [ ] **Step 5: Verify, review, and merge**

```bash
.venv/bin/python -m scripts.build_dashboard
.venv/bin/python -m unittest tests.test_dashboard -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.verify_repository
git diff --check
```

Commit message: `feat: publish final agricultural dashboard`.

DeepSeek prompt scope: data→KPI binding, privacy verifier, methodological claims and limitations.

GLM prompt scope: multi-section dashboard, KPI tiles, seven prior visualizations, accessibility and copy.

PR title: `Final project: publish agricultural analytics dashboard`.

### Task 12: Enable GitHub Pages and Perform Final Reproducibility Audit

**Files:**
- Modify only if verification finds a concrete defect in tracked project files

**Interfaces:**
- Consumes: final merged `main`
- Produces: live public repository and GitHub Pages URL

- [ ] **Step 1: Fresh local verification**

```bash
git switch main
git pull --ff-only
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.verify_repository
git diff --check
git status --short
```

Expected: all tests pass, verifier exits `0`, clean worktree.

- [ ] **Step 2: Execute all notebooks from clean kernels**

```bash
for notebook in notebooks/*.ipynb; do
  .venv/bin/jupyter nbconvert --execute --to notebook --inplace \
    --ExecutePreprocessor.cwd=. \
    --ExecutePreprocessor.timeout=1800 \
    "$notebook"
done
```

Rerun tests and confirm notebook execution produces no tracked diff. If metadata causes nondeterministic diffs, normalize only execution timestamps while retaining outputs.

- [ ] **Step 3: Verify GitHub history**

```bash
GH_TOKEN="$GITHUB_TOKEN" gh pr list --state merged --limit 20 \
  --json number,title,headRefName,mergedAt
git log --graph --oneline --decorate --all
```

Expected: nine merged feature pull requests in assignment order.

- [ ] **Step 4: Enable Pages from `main:/docs`**

```bash
GH_TOKEN="$GITHUB_TOKEN" gh api \
  --method POST repos/bayhnf/Agricultural-Data-Analytics/pages \
  -f 'source[branch]=main' \
  -f 'source[path]=/docs'
```

If Pages already exists, update it:

```bash
GH_TOKEN="$GITHUB_TOKEN" gh api \
  --method PUT repos/bayhnf/Agricultural-Data-Analytics/pages \
  -f 'source[branch]=main' \
  -f 'source[path]=/docs'
```

- [ ] **Step 5: Verify deployment and public cloning**

```bash
GH_TOKEN="$GITHUB_TOKEN" gh api \
  repos/bayhnf/Agricultural-Data-Analytics/pages/builds/latest
curl --fail --retry 12 --retry-delay 10 \
  https://bayhnf.github.io/Agricultural-Data-Analytics/ >/dev/null
temporary="$(mktemp -d)"
git clone --depth 1 \
  https://github.com/bayhnf/Agricultural-Data-Analytics.git \
  "$temporary/repo"
test -f "$temporary/repo/docs/index.html"
```

- [ ] **Step 6: Final dual-model review**

DeepSeek reviews final `main` against the approved spec and all assignment contracts.

GLM 5.2 reviews final public URLs, assignment deliverable inventory, dashboard accessibility, and evidence honesty.

Correct only verified findings through a final narrowly scoped pull request; rerun Steps 1–5 after any change.

- [ ] **Step 7: Record the user-only handoff**

Final response must include:

- public GitHub repository;
- live GitHub Pages URL;
- final verification command results;
- exact remaining user action: open the repository in VS Code on Windows and capture genuine Assignment 1 desktop evidence if the instructor requires a screenshot;
- note that the missing final rubric was not supplied, so the known dashboard contract was implemented without inventing hidden requirements.

→ skipped: backend, database, dashboard framework, synthetic fallbacks, and copied course history; add only if a newly supplied rubric explicitly requires them.
