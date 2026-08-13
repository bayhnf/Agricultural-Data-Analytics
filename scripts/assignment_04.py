"""Assignment 4: SSURGO field/soil mapping for Story County, Iowa."""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from scripts.common import download_atomic, sha256_file, write_manifest

SSURGO_URL = ("https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/"
              "wss_SSA_IA169_%5B2025-09-09%5D.zip")
ARCHIVE_NAME = "wss_SSA_IA169_[2025-09-09].zip"
SNAPSHOT_DATE = "2025-09-09"
WORK_CRS = 5070
OUTPUT_CRS = 4326
REQUIRED_MEMBERS = (
    "IA169/spatial/soilmu_a_ia169.dbf",
    "IA169/spatial/soilmu_a_ia169.prj",
    "IA169/spatial/soilmu_a_ia169.shp",
    "IA169/spatial/soilmu_a_ia169.shx",
    "IA169/tabular/mapunit.txt",
    "IA169/tabular/mstabcol.txt",
)
MAPUNIT_TABLE = "mapunit"
MAPUNIT_REQUIRED_COLUMNS = ("musym", "muname", "mukey")
FIELD_COUNT = 25


def normalize_mukey(value) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("mapunit key must not be empty")
    return text


def parse_mapunit_column_order(mstabcol_text: str) -> list[str]:
    """Resolve mapunit.txt column positions from the mstabcol metadata."""
    columns: dict[int, str] = {}
    for row in csv.reader(io.StringIO(mstabcol_text), delimiter="|"):
        if len(row) >= 3 and row[0].strip() == MAPUNIT_TABLE:
            try:
                index = int(row[1].strip())
            except ValueError:
                raise ValueError(
                    "invalid column ordinal in mstabcol.txt") from None
            name = row[2].strip()
            if index in columns and columns[index] != name:
                raise ValueError(
                    f"conflicting mapunit column {index} in mstabcol.txt")
            columns[index] = name
    if not columns:
        raise ValueError("no mapunit column metadata in mstabcol.txt")
    expected = set(range(1, max(columns) + 1))
    if set(columns) != expected:
        raise ValueError("mapunit column ordinals are not contiguous")
    missing = set(MAPUNIT_REQUIRED_COLUMNS) - set(columns.values())
    if missing:
        raise ValueError(
            "mapunit columns missing: " + ", ".join(sorted(missing)))
    return [columns[index] for index in range(1, max(columns) + 1)]


def read_mapunit_table(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read mapunit.txt using metadata-derived positions, validating shape."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for number, row in enumerate(csv.reader(stream, delimiter="|"),
                                     start=1):
            if len(row) != len(columns):
                raise ValueError(
                    f"mapunit.txt row {number} has {len(row)} fields, "
                    f"expected {len(columns)}")
            rows.append({name: value.strip()
                         for name, value in zip(columns, row)})
    if not rows:
        raise ValueError("mapunit.txt contains no data rows")
    frame = pd.DataFrame(rows)
    if frame["mukey"].duplicated().any():
        raise ValueError("duplicate mukey values in mapunit.txt")
    return frame


def calculate_field_soil_overlap(fields: gpd.GeoDataFrame,
                                 soils: gpd.GeoDataFrame) -> pd.DataFrame:
    """One row per (field, mapunit) intersection in EPSG:5070.

    Fractions are overlap area divided by whole-field area, so partial
    coverage is visible as a sum below 1.0 instead of being normalized.
    """
    if fields.crs is None or soils.crs is None:
        raise ValueError("fields and soils must declare a CRS")
    if "field_id" not in fields.columns:
        raise ValueError("fields must have a field_id column")
    if "mukey" not in soils.columns:
        raise ValueError("soils must have a mukey column")
    field_work = fields.to_crs(WORK_CRS)[["field_id", "geometry"]].copy()
    soil_work = soils.to_crs(WORK_CRS)[["mukey", "geometry"]].copy()
    soil_work["mukey"] = soil_work["mukey"].map(normalize_mukey)
    soil_work = soil_work.dissolve(by="mukey").reset_index()
    field_area = field_work.set_index("field_id").geometry.area
    if field_area.le(0).any():
        raise ValueError("field area must be positive")
    overlap = gpd.overlay(field_work, soil_work, how="intersection",
                          keep_geom_type=True)
    overlap = overlap.loc[overlap.geometry.notna()
                          & ~overlap.geometry.is_empty].copy()
    overlap["overlap_area_m2"] = overlap.geometry.area
    overlap["field_fraction"] = (
        overlap["overlap_area_m2"]
        / overlap["field_id"].map(field_area))
    return (overlap[["field_id", "mukey", "overlap_area_m2",
                     "field_fraction"]]
            .sort_values(["field_id", "mukey"], kind="stable")
            .reset_index(drop=True))


def _validate_archive(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ValueError(f"corrupt archive member {corrupt} in "
                             f"{zip_path}")
        missing = set(REQUIRED_MEMBERS) - set(archive.namelist())
        if missing:
            raise ValueError(
                "archive missing required members: " + ", ".join(
                    sorted(missing)))


def _archive_member_count(zip_path: Path) -> int:
    with zipfile.ZipFile(zip_path) as archive:
        return len(archive.namelist())


def _acquire_archive(raw_dir: Path
                     ) -> tuple[Path, str, str, bool]:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / ARCHIVE_NAME
    cached = False
    if zip_path.is_file():
        try:
            _validate_archive(zip_path)
            cached = True
        except (ValueError, zipfile.BadZipFile):
            zip_path.unlink(missing_ok=True)
    if not zip_path.is_file():
        download_atomic(SSURGO_URL, zip_path)
        try:
            _validate_archive(zip_path)
        except (ValueError, zipfile.BadZipFile):
            zip_path.unlink(missing_ok=True)
            raise
    digest = sha256_file(zip_path)
    retrieved = datetime.fromtimestamp(
        zip_path.stat().st_mtime, tz=timezone.utc).isoformat()
    return zip_path, digest, retrieved, cached


def _ensure_extracted(zip_path: Path, extract_dir: Path) -> None:
    """Extract required members, replacing any incomplete extraction."""
    extract_dir = Path(extract_dir)
    required = [extract_dir / Path(member) for member in REQUIRED_MEMBERS]
    if all(path.is_file() and path.stat().st_size > 0 for path in required):
        return
    staging = Path(str(extract_dir) + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in REQUIRED_MEMBERS:
            archive.extract(member, staging)
    shutil.rmtree(extract_dir, ignore_errors=True)
    staging.rename(extract_dir)


def build_field_soil_mapping(raw_dir: Path, fields_path: Path,
                             output_dir: Path,
                             provenance_dir: Path) -> None:
    raw_dir = Path(raw_dir)
    fields_path = Path(fields_path)
    output_dir = Path(output_dir)
    provenance_dir = Path(provenance_dir)
    ssurgo_dir = raw_dir / "ssurgo"

    fields = gpd.read_file(fields_path)
    if len(fields) != FIELD_COUNT or fields["field_id"].nunique() != FIELD_COUNT:
        raise ValueError(f"expected {FIELD_COUNT} unique selected fields")

    zip_path, digest, retrieved, cached = _acquire_archive(ssurgo_dir)
    extract_dir = ssurgo_dir / "IA169"
    _ensure_extracted(zip_path, extract_dir)

    columns = parse_mapunit_column_order(
        (extract_dir / "IA169/tabular/mstabcol.txt").read_text(
            encoding="utf-8"))
    mapunits = read_mapunit_table(
        extract_dir / "IA169/tabular/mapunit.txt", columns)

    soils = gpd.read_file(extract_dir / "IA169/spatial/soilmu_a_ia169.shp",
                          columns=["MUKEY"])
    soils["mukey"] = soils["MUKEY"].map(normalize_mukey)
    soils = soils.drop(columns=["MUKEY"]).merge(
        mapunits[["mukey", "musym", "muname"]], on="mukey", how="left")
    if soils[["musym", "muname"]].isna().any().any():
        raise ValueError("soil polygons missing mapunit tabular attributes")

    overlap = calculate_field_soil_overlap(fields, soils)
    covered_keys = set(overlap["mukey"])
    field_union = fields.to_crs(OUTPUT_CRS).geometry.union_all()
    soil_units = (gpd.clip(soils, field_union)
                  .dissolve(by="mukey")
                  .reset_index()
                  .sort_values("mukey", kind="stable")
                  .to_crs(OUTPUT_CRS))
    missing_units = covered_keys - set(soil_units["mukey"])
    if missing_units:
        raise ValueError("mapunits missing after clip: "
                         + ", ".join(sorted(missing_units)))
    output_dir.mkdir(parents=True, exist_ok=True)
    soil_units.to_file(output_dir / "soil_map_units.geojson",
                       driver="GeoJSON")

    field_areas = fields.to_crs(WORK_CRS).copy()
    field_areas["field_area_m2"] = field_areas.geometry.area
    field_areas = field_areas[["field_id", "field_area_m2"]]
    rows = overlap.merge(mapunits[["mukey", "musym", "muname"]],
                         on="mukey", how="left")
    rows = rows.merge(field_areas, on="field_id", how="left")
    uncovered = fields.loc[
        ~fields["field_id"].isin(set(rows["field_id"])), ["field_id"]].copy()
    uncovered["mukey"] = ""
    uncovered["musym"] = ""
    uncovered["muname"] = ""
    uncovered["overlap_area_m2"] = 0.0
    uncovered["field_fraction"] = 0.0
    rows = pd.concat([rows, uncovered.merge(field_areas, on="field_id",
                                            how="left")], ignore_index=True)
    rows = rows[["field_id", "mukey", "musym", "muname", "overlap_area_m2",
                 "field_area_m2", "field_fraction"]]
    rows = (rows.sort_values(["field_id", "mukey"], kind="stable")
            .reset_index(drop=True))
    rows.to_csv(output_dir / "field_soil_overlap.csv", index=False)

    write_manifest(provenance_dir / "ssurgo_ia169.json", {
        "dataset": "ssurgo_soil_map_units",
        "source_organization":
            "USDA Natural Resources Conservation Service (NRCS)",
        "source_name": "Soil Survey Geographic Database (SSURGO), "
                       "Soil Survey Area IA169 (Story County, Iowa)",
        "source_urls": [SSURGO_URL],
        "snapshot_date": SNAPSHOT_DATE,
        "archive_name": ARCHIVE_NAME,
        "retrieved_utc": retrieved,
        "sha256": {str(zip_path): digest},
        "source_crs": "EPSG:4326",
        "analysis_crs": "EPSG:5070",
        "output_crs": "EPSG:4326",
        "producer": "scripts/assignment_04.py",
        "counts": {
            "archive_members": _archive_member_count(zip_path),
            "mapunit_table_rows": int(len(mapunits)),
            "shapefile_features": int(len(soils)),
            "unique_mapunits": int(len(mapunits)),
            "overlapping_mapunits": int(len(covered_keys)),
            "overlap_rows": int(len(overlap)),
            "soil_features": int(len(soil_units)),
            "csv_rows": int(len(rows)),
            "fields": int(len(fields)),
            "cache_used": cached,
        },
        "license_note":
            "SSURGO soil data are produced and maintained by the USDA "
            "Natural Resources Conservation Service (NRCS). SSURGO maps "
            "are designed for interpretations at scales from about "
            "1:12,000 to 1:63,360 and are not intended for site-specific "
            "or larger-scale interpretations. Credit the USDA NRCS as the "
            "source of the soil data in products derived from these data.",
    })


def main() -> None:
    build_field_soil_mapping(
        raw_dir=Path("data/raw"),
        fields_path=Path(
            "data/processed/assignment-02/fields_EPSG4326.geojson"),
        output_dir=Path("data/processed/assignment-04"),
        provenance_dir=Path("data/provenance"),
    )


if __name__ == "__main__":
    main()
