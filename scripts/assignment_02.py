"""Assignment 2A: public acquisition, provenance, and deterministic field selection."""

from __future__ import annotations

import html
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
import requests
from shapely.geometry.base import BaseGeometry

from scripts.common import download_atomic, sha256_file, write_manifest
from scripts.zonal import categorical_summary

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


CDL_SERVICE_URL = ("https://nassgeodata.gmu.edu/axis2/services/CDLService/"
                   "GetCDLFile")
CDL_FIPS = "19169"
CDL_YEARS = (2020, 2021, 2022, 2023)
CDL_METADATA_URL = ("https://www.nass.usda.gov/Research_and_Science/"
                    "Cropland/metadata/metadata_ia23.htm")
MINIMUM_COVERAGE = 0.70
VERIFIED_2023_CACHE = Path(
    "/home/bell/.cache/agri-course-source-audit/CDL_2023_19169.tif")


def cdl_service_url(year: int) -> str:
    query = urlencode((("fips", CDL_FIPS), ("year", str(year))))
    return CDL_SERVICE_URL + "?" + query


def parse_return_url(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    for element in root.iter():
        if element.tag.endswith("returnURL"):
            value = (element.text or "").strip()
            if value:
                return value
            raise ValueError("empty returnURL in CDL service response")
    raise ValueError("no returnURL in CDL service response")


def parse_cdl_labels(html_text: str) -> dict[int, str]:
    labels: dict[int, str] = {}
    for block in re.findall(r"<pre>(.*?)</pre>", html_text, re.S):
        for line in html.unescape(block).splitlines():
            found = re.match(r'^\s*"(\d+)"\s+(.+?)\s*$', line)
            if found:
                code = int(found.group(1))
                name = found.group(2)
                if code in labels and labels[code] != name:
                    raise ValueError(
                        f"conflicting CDL metadata names for code {code}")
                labels[code] = name
    if not labels:
        raise ValueError("no code/name rows parsed from CDL metadata")
    return labels


def summarize_field_year(raster_path: Path, fields: gpd.GeoDataFrame,
                         minimum_coverage: float = MINIMUM_COVERAGE
                         ) -> list[dict]:
    """One majority summary per field for a single raster year."""
    if "field_id" not in fields.columns:
        raise ValueError("fields must have a field_id column")
    rows = []
    with rasterio.open(raster_path) as source:
        geometries = fields.to_crs(source.crs).geometry
        for field_id, geometry in zip(fields["field_id"], geometries):
            masked, _ = rasterio.mask.mask(source, [geometry],
                                             crop=True, filled=False)
            data = np.ma.compressed(masked[0])
            valid = data != 0
            summary = categorical_summary(data, valid, minimum_coverage)
            rows.append({"field_id": str(field_id), **summary})
    return rows


def _read_raster_profile(raster_path: Path) -> dict:
    with rasterio.open(raster_path) as source:
        array = source.read(1)
        codes, counts = np.unique(array, return_counts=True)
        return {
            "crs": source.crs.to_string(),
            "width": int(source.width),
            "height": int(source.height),
            "dtype": str(array.dtype),
            "code_counts": {int(code): int(count)
                            for code, count in zip(codes, counts)},
        }


def _fetch_metadata(url: str, destination: Path) -> tuple[str, bool]:
    if destination.is_file():
        retrieved = datetime.fromtimestamp(
            destination.stat().st_mtime, tz=timezone.utc)
        return retrieved.isoformat(), True
    response = requests.get(url, timeout=(30, 300))
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(response.text)
    return datetime.now(timezone.utc).isoformat(), False


def _acquire_cdl_raster(year: int, return_url: str, raw_dir: Path
                        ) -> tuple[Path, str, str, bool]:
    destination = raw_dir / f"CDL_{year}_{CDL_FIPS}.tif"
    if (year == 2023 and VERIFIED_2023_CACHE.is_file()
            and not destination.is_file()):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(VERIFIED_2023_CACHE, destination)
        digest = sha256_file(destination)
        retrieved = datetime.fromtimestamp(
            destination.stat().st_mtime, tz=timezone.utc).isoformat()
        return destination, digest, retrieved, True
    digest, retrieved, cached = _cached_download(return_url, destination)
    return destination, digest, retrieved, cached


def _join_crops_to_fields(fields: gpd.GeoDataFrame,
                          crops: pd.DataFrame) -> gpd.GeoDataFrame:
    metric_names = {"cdl_code": "code", "cdl_name": "name",
                    "majority_fraction": "fraction",
                    "coverage_fraction": "coverage"}
    wide = crops.pivot(index="field_id", columns="year",
                       values=list(metric_names))
    wide.columns = [f"crop_{year}_{metric_names[metric]}"
                    for metric, year in wide.columns]
    for column in wide.columns:
        if column.endswith("_code"):
            wide[column] = pd.to_numeric(wide[column]).astype("Int64")
        elif column.endswith(("_fraction", "_coverage")):
            wide[column] = pd.to_numeric(wide[column], errors="coerce")
    return gpd.GeoDataFrame(fields.merge(wide.reset_index(),
                                         on="field_id"),
                            crs=fields.crs)


def _write_summary(fields: gpd.GeoDataFrame, crops: pd.DataFrame,
                   path: Path) -> None:
    summary = pd.DataFrame([{
        "field_count": int(len(fields)),
        "total_area_ha": float(fields["area_ha"].sum()),
        "mean_area_ha": float(fields["area_ha"].mean()),
        "median_area_ha": float(fields["area_ha"].median()),
        "crop_record_count": int(len(crops)),
        "missing_crop_record_count": int(crops["cdl_code"].isna().sum()),
        "duplicate_field_id_count": int(
            crops.duplicated(["field_id", "year"]).sum()),
    }])
    summary.to_csv(path, index=False)


MAP_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Story County field crop history 2020-2023</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html, body, #map {height: 100%; margin: 0;}</style>
</head>
<body>
<div id="map"></div>
<script>
var fields = __FIELDS_GEOJSON__;
var fieldsLayer = L.geoJSON(fields, {onEachFeature: function (feature, layer) {
    var props = feature.properties;
    var lines = [2020, 2021, 2022, 2023].map(function (year) {
        return year + ": " + (props["crop_" + year + "_name"] || "n/a");
    });
    layer.bindPopup("<b>" + props.field_id + "</b><br>" + lines.join("<br>"));
}});
var map = L.map("map").fitBounds(fieldsLayer.getBounds());
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);
fieldsLayer.addTo(map);
</script>
</body>
</html>
"""

def _write_map(joined: gpd.GeoDataFrame, path: Path) -> None:
    payload = json.loads(joined.to_json())
    path.write_text(MAP_HTML_TEMPLATE.replace(
        "__FIELDS_GEOJSON__",
        json.dumps(payload, separators=(",", ":"))),
        encoding="utf-8")


def build_cdl_products(fields_path: Path, raw_dir: Path, output_dir: Path,
                       provenance_dir: Path) -> None:
    fields_path = Path(fields_path)
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    provenance_dir = Path(provenance_dir)

    fields = gpd.read_file(fields_path)

    metadata_path = raw_dir / "cdl_metadata_ia23.htm"
    metadata_retrieved, metadata_cached = _fetch_metadata(
        CDL_METADATA_URL, metadata_path)
    try:
        labels = parse_cdl_labels(metadata_path.read_text(errors="replace"))
    except ValueError:
        metadata_path.unlink(missing_ok=True)
        raise

    records = []
    year_info = {}
    for year in CDL_YEARS:
        service_url = cdl_service_url(year)
        response = requests.get(service_url, timeout=(30, 300))
        response.raise_for_status()
        return_url = parse_return_url(response.text)
        raster_path, digest, retrieved, cached = _acquire_cdl_raster(
            year, return_url, raw_dir)
        profile = _read_raster_profile(raster_path)
        for row in summarize_field_year(raster_path, fields):
            code = row["value"]
            name = None if code is None else labels.get(code)
            if code is not None and name is None:
                raise ValueError(
                    f"CDL code {code} ({year}) missing from the official "
                    "metadata domain")
            records.append({
                "field_id": row["field_id"],
                "year": year,
                "cdl_code": code,
                "cdl_name": name,
                "majority_fraction": row["majority_fraction"],
                "coverage_fraction": row["coverage_fraction"],
                "valid_pixels": row["valid_pixels"],
                "total_pixels": row["total_pixels"],
            })
        year_info[str(year)] = {
            "service_url": service_url,
            "return_url": return_url,
            "sha256": digest,
            "retrieved_utc": retrieved,
            "cache_used": cached,
            "raster_path": str(raster_path),
            **profile,
        }

    crops = (pd.DataFrame(records)
             .sort_values(["field_id", "year"], kind="stable")
             .reset_index(drop=True))
    output_dir.mkdir(parents=True, exist_ok=True)
    crops.to_csv(output_dir / "cdl_EPSG4326.csv", index=False)

    joined = _join_crops_to_fields(fields, crops)
    joined.to_file(output_dir / "fields_with_crops.geojson",
                   driver="GeoJSON")
    _write_summary(fields, crops, output_dir / "field_summary.csv")
    _write_map(joined, output_dir / "my_fields_map.html")

    write_manifest(provenance_dir / "cdl_2020_2023.json", {
        "dataset": "cdl_crop_history",
        "source_organization":
            "USDA National Agricultural Statistics Service (NASS)",
        "source_name":
            "Cropland Data Layer (CDL), Story County, Iowa, 2020-2023",
        "source_urls": [year_info[str(year)]["return_url"]
                        for year in CDL_YEARS],
        "service_urls": {str(year): year_info[str(year)]["service_url"]
                         for year in CDL_YEARS},
        "retrieved_utc": max(
            year_info[str(year)]["retrieved_utc"] for year in CDL_YEARS),
        "source_version": "2020-2023",
        "sha256": {year_info[str(year)]["raster_path"]:
                   year_info[str(year)]["sha256"]
                   for year in CDL_YEARS},
        "source_crs": {str(year): year_info[str(year)]["crs"]
                       for year in CDL_YEARS},
        "output_crs": "EPSG:4326",
        "producer": "scripts/assignment_02.py",
        "years": list(CDL_YEARS),
        "official_metadata_url": CDL_METADATA_URL,
        "dimensions": {str(year): {
            "width": year_info[str(year)]["width"],
            "height": year_info[str(year)]["height"],
            "dtype": year_info[str(year)]["dtype"],
        } for year in CDL_YEARS},
        "code_counts": {str(year): year_info[str(year)]["code_counts"]
                        for year in CDL_YEARS},
        "counts": {
            "fields": int(len(fields)),
            "crop_records": int(len(crops)),
            "joined_features": int(len(joined)),
            "summary_rows": 1,
            "metadata_cache_used": metadata_cached,
            "metadata_retrieved_utc": metadata_retrieved,
            "cache_used": {str(year): year_info[str(year)]["cache_used"]
                           for year in CDL_YEARS},
        },
        "license_note":
            "USDA NASS Cropland Data Layer is public domain and free to "
            "redistribute (official metadata statement); field polygons "
            "derive from public-domain USDA ACPF and U.S. Census TIGER data.",
    })


def main() -> None:
    raw_dir = Path("data/raw")
    output_dir = Path("data/processed/assignment-02")
    provenance_dir = Path("data/provenance")
    build_fields(raw_dir, output_dir, provenance_dir)
    build_cdl_products(output_dir / "fields_EPSG4326.geojson",
                       raw_dir, output_dir, provenance_dir)


if __name__ == "__main__":
    main()
