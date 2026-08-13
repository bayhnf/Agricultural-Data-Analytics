"""Assignment 2A: public acquisition, provenance, and deterministic field selection."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from scripts.common import download_atomic, sha256_file, write_manifest

COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
              "TIGERweb/State_County/MapServer/1/query")
COUNTY_QUERY = {
    "where": "GEOID='19169'",
    "outFields": "GEOID,NAME",
    "returnGeometry": "true",
    "f": "geojson",
}
ACPF_URL = "https://ndownloader.figshare.com/files/44528942"
ACPF_SHA256 = "ef9e42cf4456da0c05b68db25a5f8fc02ac11d2ecd9d75fbe4ef741ebe56118f"
ACPF_LAYER = "IowaFieldBoundaries2019.shp"
ACPF_MEMBERS = (
    "IowaFieldBoundaries2019.cpg",
    "IowaFieldBoundaries2019.dbf",
    "IowaFieldBoundaries2019.prj",
    "IowaFieldBoundaries2019.shp",
    "IowaFieldBoundaries2019.shx",
)
GRID_SIZE = 5


def select_grid_fields(fields: gpd.GeoDataFrame,
                       county: BaseGeometry) -> gpd.GeoDataFrame:
    """Select one eligible field per 5 x 5 EPSG:5070 grid cell over the county."""
    if fields.crs is None:
        raise ValueError("fields must declare a CRS")
    work = fields.to_crs(5070).copy()
    missing = {"FBndID", "isAG"} - set(work.columns)
    if missing:
        raise ValueError("fields missing required columns: "
                         + ", ".join(sorted(missing)))
    geometry = work.geometry
    keep = ((work["isAG"] == 1) & geometry.notna()
            & ~geometry.is_empty & geometry.is_valid)
    work = work.loc[keep].drop_duplicates(
        subset="FBndID", keep="first").copy()
    work["_area"] = work.geometry.area
    work = work.loc[work["_area"] > 0].copy()
    work["_centroid"] = work.geometry.centroid
    work["_inside_fraction"] = (
        work.geometry.intersection(county).area / work["_area"])
    work = work.loc[work["_centroid"].within(county)
                    & (work["_inside_fraction"] >= 0.95)].copy()

    minx, miny, maxx, maxy = county.bounds
    cell_width = (maxx - minx) / GRID_SIZE
    cell_height = (maxy - miny) / GRID_SIZE
    work["_grid_col"] = ((work["_centroid"].x - minx)
                         / cell_width).astype("int64").clip(0, GRID_SIZE - 1)
    work["_grid_row"] = ((maxy - work["_centroid"].y)
                         / cell_height).astype("int64").clip(0, GRID_SIZE - 1)
    populated = set(zip(work["_grid_row"], work["_grid_col"]))
    if len(populated) < GRID_SIZE * GRID_SIZE:
        raise ValueError(
            f"expected 25 populated grid cells, found {len(populated)}")

    records = []
    for grid_row in range(GRID_SIZE):
        for grid_col in range(GRID_SIZE):
            center_x = minx + (grid_col + 0.5) * cell_width
            center_y = maxy - (grid_row + 0.5) * cell_height
            cell = work.loc[(work["_grid_row"] == grid_row)
                            & (work["_grid_col"] == grid_col)].copy()
            cell["_distance2"] = ((cell["_centroid"].x - center_x) ** 2
                                  + (cell["_centroid"].y - center_y) ** 2)
            cell["_fbndid"] = cell["FBndID"].astype(str)
            best = cell.sort_values(
                ["_distance2", "_fbndid"], kind="stable").iloc[0]
            records.append({
                "field_id": f"STORY-{len(records) + 1:02d}",
                "source_id": best["FBndID"],
                "grid_row": int(grid_row),
                "grid_col": int(grid_col),
                "area_ha": float(best.geometry.area) / 10000.0,
                "inside_fraction": float(best["_inside_fraction"]),
                "geometry": best.geometry,
            })
    return gpd.GeoDataFrame(records, crs=5070)


def _cached_download(url: str, destination: Path,
                     expected_sha256: str | None = None
                     ) -> tuple[str, str, bool]:
    if destination.is_file():
        digest = sha256_file(destination)
        if expected_sha256 and digest != expected_sha256:
            destination.unlink(missing_ok=True)
        else:
            retrieved = datetime.fromtimestamp(
                destination.stat().st_mtime, tz=timezone.utc)
            return digest, retrieved.isoformat(), True
    digest = download_atomic(url, destination, expected_sha256)
    return digest, datetime.now(timezone.utc).isoformat(), False


def _extract_acpf(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in ACPF_MEMBERS:
            archive.extract(member, extract_dir)
    return extract_dir / ACPF_LAYER


def _read_county(path: Path) -> gpd.GeoDataFrame:
    try:
        payload = json.loads(path.read_text())
        if payload.get("type") != "FeatureCollection":
            raise ValueError("not a FeatureCollection")
        if not payload.get("features"):
            raise ValueError("no features")
    except (ValueError, json.JSONDecodeError) as error:
        path.unlink(missing_ok=True)
        raise ValueError(f"invalid county GeoJSON at {path} ({error}); "
                         "deleted, rerun to retry") from error
    return gpd.GeoDataFrame.from_features(payload["features"],
                                          crs="EPSG:4326")


def build_fields(raw_dir: Path, output_dir: Path,
                 provenance_dir: Path) -> None:
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    provenance_dir = Path(provenance_dir)

    county_url = COUNTY_URL + "?" + urlencode(COUNTY_QUERY)
    county_path = raw_dir / "story_county.geojson"
    county_digest, county_retrieved, county_cached = _cached_download(
        county_url, county_path)
    county_frame = _read_county(county_path)
    if len(county_frame) != 1:
        raise ValueError(f"expected 1 Story County feature, found "
                         f"{len(county_frame)}")
    county = county_frame.geometry.union_all()
    county_5070 = gpd.GeoSeries(
        [county], crs=county_frame.crs).to_crs(5070).iloc[0]

    acpf_zip = raw_dir / "IA_ACPFfields2019.zip"
    acpf_digest, acpf_retrieved, acpf_cached = _cached_download(
        ACPF_URL, acpf_zip, ACPF_SHA256)
    acpf_dir = raw_dir / "acpf"
    layer_path = acpf_dir / ACPF_LAYER
    if not layer_path.is_file():
        layer_path = _extract_acpf(acpf_zip, acpf_dir)
    fields = gpd.read_file(layer_path, columns=["FBndID", "isAG"],
                           bbox=county_5070.bounds)
    acpf_source_crs = fields.crs.to_string() if fields.crs is not None else None

    selected = select_grid_fields(fields, county_5070)
    output = (selected.to_crs(4326)
              .sort_values("field_id").reset_index(drop=True))
    output_dir.mkdir(parents=True, exist_ok=True)
    output.to_file(output_dir / "fields_EPSG4326.geojson", driver="GeoJSON")

    write_manifest(provenance_dir / "story_county.json", {
        "dataset": "story_county_boundary",
        "source_organization": "U.S. Census Bureau",
        "source_name": "TIGERweb State_County boundary, Story County, Iowa",
        "source_urls": [county_url],
        "retrieved_utc": county_retrieved,
        "source_version": "TIGERweb State_County MapServer layer 1 snapshot",
        "sha256": {str(county_path): county_digest},
        "source_crs": "EPSG:4326",
        "output_crs": "EPSG:4326",
        "producer": "scripts/assignment_02.py",
        "counts": {"features": int(len(county_frame)),
                   "cache_used": county_cached},
        "license_note": "U.S. Census Bureau TIGER/Line data are U.S. "
                        "Government work and are in the public domain.",
    })
    write_manifest(provenance_dir / "acpf_fields.json", {
        "dataset": "acpf_fields",
        "source_organization": "USDA Agricultural Research Service (ACPF)",
        "source_name": "Iowa Field Boundaries 2019",
        "source_urls": [ACPF_URL],
        "retrieved_utc": acpf_retrieved,
        "source_version": "2019",
        "sha256": {str(acpf_zip): acpf_digest},
        "source_crs": acpf_source_crs,
        "output_crs": "EPSG:4326",
        "producer": "scripts/assignment_02.py",
        "counts": {"features_read": int(len(fields)),
                   "selected_fields": int(len(output)),
                   "cache_used": acpf_cached},
        "license_note": "ACPF field boundaries are USDA ARS public-domain "
                        "field-analysis polygons derived from edited "
                        "historical FSA Common Land Unit data; they do not "
                        "represent current ownership or program boundaries.",
    })


if __name__ == "__main__":
    build_fields(Path("data/raw"), Path("data/processed/assignment-02"),
                 Path("data/provenance"))
