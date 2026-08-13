"""Assignment 5: real Sentinel-2 imagery, cloud mask, and NDVI."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.warp
import rasterio.windows
import requests
from rasterio.enums import Resampling
from rasterio.plot import plotting_extent

from scripts.common import sha256_file, write_manifest
from scripts.zonal import continuous_summary

matplotlib.use("Agg")
from matplotlib import pyplot as plt

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION_ID = "sentinel-2-l2a"
DATE_RANGE = "2023-06-01T00:00:00Z/2023-08-31T23:59:59Z"
VALID_SCL_CLASSES = (4, 5, 6, 7)
MINIMUM_VALID_FRACTION = 0.70
ASSET_NAMES = ("red", "nir", "scl")

ROOT = Path(__file__).resolve().parents[1]
FIELDS_PATH = ROOT / "data/processed/assignment-02/fields_EPSG4326.geojson"
RAW_DIR = ROOT / "data/raw/sentinel"
OUTPUT_DIR = ROOT / "data/processed/assignment-05"
PROVENANCE_PATH = ROOT / "data/provenance/sentinel_2023.json"
RED_PNG_PATH = ROOT / "docs/assets/sentinel_red_band.png"
NDVI_PNG_PATH = ROOT / "docs/assets/ndvi_map.png"


def valid_scl_mask(scl: np.ndarray) -> np.ndarray:
    """Return pixels in vegetation, bare-soil, water, or unclassified classes."""
    return np.isin(np.asarray(scl), VALID_SCL_CLASSES)


def valid_scl_fraction(scl: np.ndarray, field_mask: np.ndarray) -> float:
    """Return the valid-SCL fraction among pixels inside selected fields."""
    scl = np.asarray(scl)
    field_mask = np.asarray(field_mask, dtype=bool)
    if scl.shape != field_mask.shape:
        raise ValueError("SCL and field mask shapes differ")
    total = int(np.count_nonzero(field_mask))
    if not total:
        return 0.0
    return float(np.count_nonzero(valid_scl_mask(scl) & field_mask) / total)


def raster_data_mask(values: np.ndarray, nodata: float | None) -> np.ndarray:
    """Return finite pixels that are not the raster's declared nodata value."""
    values = np.asarray(values)
    valid = np.isfinite(values)
    if nodata is not None and math.isfinite(float(nodata)):
        valid &= values != nodata
    return valid


def calculate_ndvi(
    red: np.ndarray,
    nir: np.ndarray,
    scale: float,
    offset: float,
    valid_mask: np.ndarray,
    *,
    nir_scale: float | None = None,
    nir_offset: float | None = None,
) -> np.ndarray:
    """Apply each asset's STAC transform and calculate masked, clipped NDVI."""
    red = np.asarray(red, dtype=float) * float(scale) + float(offset)
    nir = (
        np.asarray(nir, dtype=float)
        * float(scale if nir_scale is None else nir_scale)
        + float(offset if nir_offset is None else nir_offset)
    )
    valid = np.asarray(valid_mask, dtype=bool)
    if red.shape != nir.shape or red.shape != valid.shape:
        raise ValueError("red, NIR, and valid mask shapes differ")

    denominator = nir + red
    keep = (
        valid
        & np.isfinite(red)
        & np.isfinite(nir)
        & np.isfinite(denominator)
        & (denominator != 0)
    )
    result = np.full(red.shape, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        result[keep] = (nir[keep] - red[keep]) / denominator[keep]
    result[keep] = np.clip(result[keep], -1.0, 1.0)
    return result


def candidate_sort_key(feature: dict) -> tuple[float, str, str]:
    """Sort by cloud cover, datetime, then scene ID exactly as specified."""
    properties = feature["properties"]
    cloud_cover = properties.get("eo:cloud_cover", float("inf"))
    if cloud_cover is None:
        cloud_cover = float("inf")
    return float(cloud_cover), properties["datetime"], feature["id"]


def sort_candidates(features: list[dict]) -> list[dict]:
    return sorted(features, key=candidate_sort_key)


def select_scene_candidate(features: list[dict], reader):
    """Select the first sorted scene with at least 70% valid field pixels."""
    rejected = []
    for feature in sort_candidates(features):
        scl, field_mask = reader(feature)
        fraction = valid_scl_fraction(scl, field_mask)
        if fraction >= MINIMUM_VALID_FRACTION:
            return feature, fraction, rejected
        rejected.append({
            "scene_id": feature["id"],
            "valid_scl_fraction": fraction,
        })
    raise ValueError(
        f"no scene meets the {MINIMUM_VALID_FRACTION:.2f} "
        "valid-SCL threshold")


def stac_search_payload(bounds) -> dict:
    return {
        "collections": [COLLECTION_ID],
        "bbox": [float(value) for value in bounds],
        "datetime": DATE_RANGE,
        "limit": 100,
    }


def _assert_stac_complete(payload: dict, features: list[dict]) -> None:
    """Reject truncated responses rather than sorting an incomplete catalog."""
    context = payload.get("context")
    matched = context.get("matched") if isinstance(context, dict) else None
    if matched is not None:
        if int(matched) > len(features):
            raise ValueError(
                f"Earth Search response is truncated: {matched} matched but "
                f"only {len(features)} features returned")
        return
    if any(link.get("rel") == "next" for link in payload.get("links") or []):
        raise ValueError(
            "Earth Search response is paginated; expected one complete page")


def query_candidates(fields: gpd.GeoDataFrame) -> list[dict]:
    response = requests.post(
        EARTH_SEARCH_URL,
        json=stac_search_payload(fields.to_crs(4326).total_bounds),
        timeout=(30, 120),
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Earth Search returned no Sentinel-2 candidates")
    _assert_stac_complete(payload, features)
    for feature in features:
        missing = set(ASSET_NAMES) - set(feature.get("assets", {}))
        if missing:
            raise ValueError(
                f"scene {feature.get('id')} missing assets: "
                + ", ".join(sorted(missing)))
        candidate_sort_key(feature)
    return features


def _asset_transform(asset: dict) -> tuple[float, float]:
    bands = asset.get("raster:bands")
    if not isinstance(bands, list) or not bands:
        raise ValueError("STAC asset has no raster:bands metadata")
    band = bands[0]
    return float(band.get("scale", 1.0)), float(band.get("offset", 0.0))


def _integer_window(bounds, transform, width: int, height: int):
    raw = rasterio.windows.from_bounds(*bounds, transform=transform)
    left = max(0, math.floor(raw.col_off))
    top = max(0, math.floor(raw.row_off))
    right = min(width, math.ceil(raw.col_off + raw.width))
    bottom = min(height, math.ceil(raw.row_off + raw.height))
    if right <= left or bottom <= top:
        raise ValueError("selected fields do not intersect the raster")
    return rasterio.windows.Window(left, top, right - left, bottom - top)


def _cache_path(raw_dir: Path, feature: dict, asset_name: str) -> Path:
    return raw_dir / f"{feature['id']}_{asset_name}.tif"


def _write_cached_window(
    destination: Path,
    array: np.ndarray,
    *,
    crs,
    transform,
    nodata,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.tif")
    try:
        with rasterio.open(
            temporary,
            "w",
            driver="GTiff",
            width=array.shape[1],
            height=array.shape[0],
            count=1,
            dtype=array.dtype,
            crs=crs,
            transform=transform,
            nodata=nodata,
            compress="deflate",
        ) as target:
            target.write(array, 1)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_asset_window(
    feature: dict,
    asset_name: str,
    fields: gpd.GeoDataFrame,
    raw_dir: Path,
) -> dict:
    """Read and cache one georeferenced COG window covering every field."""
    cache_path = _cache_path(Path(raw_dir), feature, asset_name)
    cached = cache_path.is_file()
    asset = feature["assets"][asset_name]
    source_path = cache_path if cached else asset["href"]
    environment = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    }
    with rasterio.Env(**environment), rasterio.open(source_path) as source:
        if source.crs is None:
            raise ValueError(f"{asset_name} raster has no CRS")
        fields_native = fields.to_crs(source.crs)
        bounds = fields_native.total_bounds
        if not (
            source.bounds.left <= bounds[0]
            and source.bounds.bottom <= bounds[1]
            and source.bounds.right >= bounds[2]
            and source.bounds.top >= bounds[3]
        ):
            raise ValueError(
                f"scene {feature['id']} does not cover every selected field")
        window = _integer_window(
            bounds, source.transform, source.width, source.height)
        array = source.read(1, window=window)
        transform = source.window_transform(window)
        crs = source.crs
        nodata = source.nodata
    if not cached:
        _write_cached_window(
            cache_path, array, crs=crs, transform=transform, nodata=nodata)
    return {
        "array": array,
        "transform": transform,
        "crs": crs,
        "nodata": nodata,
        "path": cache_path,
        "cached": cached,
        "source_url": asset["href"],
    }


def rasterize_fields(
    fields: gpd.GeoDataFrame,
    *,
    crs,
    transform,
    shape: tuple[int, int],
) -> np.ndarray:
    geometries = [
        (geometry, 1)
        for geometry in fields.to_crs(crs).geometry
        if geometry is not None and not geometry.is_empty
    ]
    if not geometries:
        raise ValueError("no field geometries to rasterize")
    return rasterio.features.rasterize(
        geometries,
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)


def _reproject_scl(scl: dict, target: dict) -> np.ndarray:
    destination = np.zeros(target["array"].shape, dtype="uint8")
    rasterio.warp.reproject(
        source=scl["array"],
        destination=destination,
        src_transform=scl["transform"],
        src_crs=scl["crs"],
        src_nodata=scl["nodata"],
        dst_transform=target["transform"],
        dst_crs=target["crs"],
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    return destination


def _validate_reflectance_grids(red: dict, nir: dict) -> None:
    if red["array"].shape != nir["array"].shape:
        raise ValueError("red and NIR raster shapes differ")
    if red["crs"] != nir["crs"]:
        raise ValueError("red and NIR raster CRS values differ")
    if not red["transform"].almost_equals(nir["transform"]):
        raise ValueError("red and NIR raster grids differ")


def _field_summaries(
    fields: gpd.GeoDataFrame,
    ndvi: np.ndarray,
    *,
    crs,
    transform,
) -> pd.DataFrame:
    rows = []
    native = fields.to_crs(crs)
    for field_id, geometry in zip(native["field_id"], native.geometry):
        field_mask = rasterio.features.rasterize(
            [(geometry, 1)],
            out_shape=ndvi.shape,
            transform=transform,
            fill=0,
            dtype="uint8",
        ).astype(bool)
        values = ndvi[field_mask]
        summary = continuous_summary(values, np.isfinite(values))
        rows.append({
            "field_id": str(field_id),
            "mean_ndvi": summary["mean"],
            "median_ndvi": summary["median"],
            "valid_pixel_count": summary["valid_pixels"],
            "total_pixel_count": summary["total_pixels"],
            "coverage_fraction": summary["coverage_fraction"],
        })
    result = pd.DataFrame(rows).sort_values("field_id", kind="stable")
    if len(result) != 25 or result["field_id"].nunique() != 25:
        raise ValueError("expected one NDVI summary for each of 25 fields")
    return result


def _plot_outputs(
    fields: gpd.GeoDataFrame,
    feature: dict,
    red: dict,
    red_reflectance: np.ndarray,
    red_valid: np.ndarray,
    ndvi: np.ndarray,
) -> None:
    RED_PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    extent = plotting_extent(
        red["array"], transform=red["transform"])
    outlines = fields.to_crs(red["crs"])

    visible_red = np.where(red_valid, red_reflectance, np.nan)
    finite_red = visible_red[np.isfinite(visible_red)]
    if not finite_red.size:
        raise ValueError("selected red-band window has no finite data")
    lower, upper = np.nanpercentile(finite_red, [2, 98])
    figure, axis = plt.subplots(figsize=(8, 8))
    image = axis.imshow(
        visible_red,
        extent=extent,
        cmap="gray",
        vmin=float(lower),
        vmax=float(upper),
    )
    outlines.boundary.plot(ax=axis, color="#00ffff", linewidth=0.7)
    figure.colorbar(image, ax=axis, label="Red surface reflectance")
    axis.set_title(
        f"Sentinel-2 red band — {feature['properties']['datetime'][:10]}")
    axis.set_xlabel(f"Easting ({red['crs']})")
    axis.set_ylabel(f"Northing ({red['crs']})")
    figure.tight_layout()
    figure.savefig(RED_PNG_PATH, dpi=160)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 8))
    image = axis.imshow(
        np.ma.masked_invalid(ndvi),
        extent=extent,
        cmap="RdYlGn",
        vmin=-1,
        vmax=1,
    )
    outlines.boundary.plot(ax=axis, color="black", linewidth=0.7)
    figure.colorbar(image, ax=axis, label="NDVI")
    axis.set_title(
        f"Cloud-masked field NDVI — "
        f"{feature['properties']['datetime'][:10]}")
    axis.set_xlabel(f"Easting ({red['crs']})")
    axis.set_ylabel(f"Northing ({red['crs']})")
    figure.tight_layout()
    figure.savefig(NDVI_PNG_PATH, dpi=160)
    plt.close(figure)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def build_sentinel_ndvi(
    fields_path: Path = FIELDS_PATH,
    raw_dir: Path = RAW_DIR,
    output_dir: Path = OUTPUT_DIR,
    provenance_path: Path = PROVENANCE_PATH,
) -> None:
    fields = gpd.read_file(fields_path)
    if fields.crs is None:
        raise ValueError("selected fields have no CRS")
    if (
        len(fields) != 25
        or fields["field_id"].nunique() != 25
        or fields.geometry.isna().any()
        or fields.geometry.is_empty.any()
    ):
        raise ValueError("expected 25 unique non-empty selected fields")

    candidates = query_candidates(fields)

    scl_windows = {}

    def candidate_scl(feature):
        scl = read_asset_window(feature, "scl", fields, raw_dir)
        scl_windows[feature["id"]] = scl
        field_mask = rasterize_fields(
            fields,
            crs=scl["crs"],
            transform=scl["transform"],
            shape=scl["array"].shape,
        )
        return scl["array"], field_mask

    selected, valid_fraction, rejected = select_scene_candidate(
        candidates, candidate_scl)
    red = read_asset_window(selected, "red", fields, raw_dir)
    nir = read_asset_window(selected, "nir", fields, raw_dir)
    scl = scl_windows[selected["id"]]
    _validate_reflectance_grids(red, nir)

    red_scale, red_offset = _asset_transform(selected["assets"]["red"])
    nir_scale, nir_offset = _asset_transform(selected["assets"]["nir"])
    scl_10m = _reproject_scl(scl, red)
    field_mask = rasterize_fields(
        fields,
        crs=red["crs"],
        transform=red["transform"],
        shape=red["array"].shape,
    )
    red_data = raster_data_mask(red["array"], red["nodata"])
    nir_data = raster_data_mask(nir["array"], nir["nodata"])
    valid = field_mask & valid_scl_mask(scl_10m) & red_data & nir_data
    ndvi = calculate_ndvi(
        red["array"],
        nir["array"],
        red_scale,
        red_offset,
        valid,
        nir_scale=nir_scale,
        nir_offset=nir_offset,
    )
    summaries = _field_summaries(
        fields, ndvi, crs=red["crs"], transform=red["transform"])
    if summaries[["mean_ndvi", "median_ndvi"]].isna().any().any():
        raise ValueError("at least one field has no valid NDVI pixels")

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries.to_csv(output_dir / "field_ndvi.csv", index=False)
    assets = {"red": red, "nir": nir, "scl": scl}
    cache_paths = {name: data["path"] for name, data in assets.items()}
    scene = {
        "collection": COLLECTION_ID,
        "search_datetime": DATE_RANGE,
        "selected_scene_id": selected["id"],
        "selected_scene_datetime": selected["properties"]["datetime"],
        "selected_scene_cloud_cover": selected["properties"].get(
            "eo:cloud_cover"),
        "study_area_valid_scl_fraction": valid_fraction,
        "minimum_valid_scl_fraction": MINIMUM_VALID_FRACTION,
        "valid_scl_classes": list(VALID_SCL_CLASSES),
        "rejected_candidates": rejected,
        "assets": {
            "red": {
                "scale": red_scale,
                "offset": red_offset,
                "cache_file": str(cache_paths["red"].relative_to(ROOT)),
            },
            "nir": {
                "scale": nir_scale,
                "offset": nir_offset,
                "cache_file": str(cache_paths["nir"].relative_to(ROOT)),
            },
            "scl": {
                "resampling_to_red_grid": "nearest",
                "cache_file": str(cache_paths["scl"].relative_to(ROOT)),
            },
        },
    }
    _write_json(output_dir / "scene.json", scene)

    red_reflectance = (
        red["array"].astype(float) * red_scale + red_offset)
    _plot_outputs(
        fields, selected, red, red_reflectance, red_data, ndvi)

    retrieved = datetime.fromtimestamp(
        max(path.stat().st_mtime for path in cache_paths.values()),
        tz=timezone.utc,
    ).isoformat()
    sha256 = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in cache_paths.values()
    }
    write_manifest(provenance_path, {
        "dataset": "sentinel_2_field_ndvi",
        "source_organization":
            "European Space Agency Copernicus Programme, "
            "catalogued by Element 84",
        "source_name": "Sentinel-2 Level-2A surface reflectance",
        "source_urls": [
            EARTH_SEARCH_URL,
            red["source_url"],
            nir["source_url"],
            scl["source_url"],
        ],
        "retrieved_utc": retrieved,
        "source_version": selected["id"],
        "sha256": sha256,
        "source_crs": red["crs"].to_string(),
        "output_crs":
            "not applicable (scalar field summaries keyed by field_id)",
        "producer": "scripts/assignment_05.py",
        "counts": {
            "candidates_returned": len(candidates),
            "candidates_rejected": len(rejected),
            "fields": len(fields),
            "csv_rows": len(summaries),
            "study_area_total_pixels": int(np.count_nonzero(field_mask)),
            "study_area_valid_pixels": int(np.count_nonzero(valid)),
            "cache_used": {
                "red": red["cached"],
                "nir": nir["cached"],
                "scl": scl["cached"],
            },
        },
        "license_note":
            "Contains modified Copernicus Sentinel data (2023), processed "
            "by ESA and accessed through the Element 84 Earth Search "
            "public-data catalog.",
    })
    print(
        f"selected {selected['id']} at {valid_fraction:.3f} valid SCL; "
        f"wrote {len(summaries)} field summaries")


def main() -> None:
    build_sentinel_ndvi()


if __name__ == "__main__":
    main()
