"""Task 11 slice A: deterministic dashboard data from committed products."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from scripts.common import write_manifest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs/data/dashboard.json"
FIELD_COUNT = 25

INPUT_RELATIVE_PATHS = {
    "field_summary": "data/processed/assignment-02/field_summary.csv",
    "crops": "data/processed/assignment-02/cdl_EPSG4326.csv",
    "ndvi": "data/processed/assignment-05/field_ndvi.csv",
    "scene": "data/processed/assignment-05/scene.json",
    "weather": "data/processed/assignment-06/weather_summary.json",
    "soil": "data/processed/assignment-08/soil_health_summary.json",
}

SOIL_METRICS = {
    "mean_organic_matter_pct": "organic_matter_pct",
    "mean_ph": "ph_h2o",
    "mean_cec_cmol_kg": "cec_cmol_kg",
    "mean_carbon_storage_mg_c_ha": "carbon_storage_mg_c_ha",
}

FINITE_KEYS = frozenset({
    "field_count",
    "total_area_ha",
    "mean_ndvi",
    "ndvi_coverage_pct",
    "t2m_anomaly_2023_c",
    "precip_2023_mm",
    "mean_organic_matter_pct",
    "mean_ph",
    "mean_cec_cmol_kg",
    "mean_carbon_storage_mg_c_ha",
})

BASE_SOURCES = {
    "fields": {
        "organization": "USDA Agricultural Research Service",
        "name": "Iowa Field Boundaries 2019 (ACPF)",
        "version": "2019",
    },
    "crops": {
        "organization": "USDA National Agricultural Statistics Service",
        "name": "Cropland Data Layer, Story County, Iowa",
        "version": "2020-2023",
    },
    "ndvi": {
        "organization": "European Space Agency Copernicus Programme",
        "name": "Sentinel-2 Level-2A surface reflectance",
        "license_note": "Contains modified Copernicus Sentinel data 2023",
    },
    "weather": {
        "organization": "NASA Langley Research Center",
        "name": "POWER daily point data (T2M, PRECTOTCORR)",
        "version": "1991-2023",
    },
    "soil": {
        "organization": "USDA Natural Resources Conservation Service",
        "name": "SSURGO Soil Survey Area IA169, Story County, Iowa",
        "version": "2025-09-09 snapshot",
    },
    "units": {
        "field_count": "fields",
        "total_area_ha": "ha",
        "dominant_crop_2023": "crop name by largest 2023 valid-pixel area",
        "mean_ndvi": "unitless NDVI (-1 to 1)",
        "ndvi_coverage_pct": "% of field pixels",
        "scene_date": "YYYY-MM-DD",
        "t2m_anomaly_2023_c": "°C, 2023 vs 1991-2020 daily baseline",
        "precip_2023_mm": "mm, 2023 total",
        "mean_organic_matter_pct": "%",
        "mean_ph": "pH units",
        "mean_cec_cmol_kg": "cmol(+)/kg",
        "mean_carbon_storage_mg_c_ha": "Mg C/ha",
    },
}


def require_inputs(root: Path) -> dict[str, Path]:
    missing = sorted(
        name for name, relative in INPUT_RELATIVE_PATHS.items()
        if not (root / relative).is_file())
    if missing:
        raise FileNotFoundError(
            "missing dashboard inputs: " + ", ".join(missing))
    return {name: root / relative
            for name, relative in INPUT_RELATIVE_PATHS.items()}


def require_field_rows(frame: pd.DataFrame, label: str) -> None:
    if len(frame) != FIELD_COUNT:
        raise ValueError(
            f"{label}: expected {FIELD_COUNT} rows, found {len(frame)}")
    field_ids = frame["field_id"]
    if (field_ids.isna().any() or field_ids.duplicated().any()
            or field_ids.nunique() != FIELD_COUNT):
        raise ValueError(
            f"{label}: expected {FIELD_COUNT} unique field ids")


def require_finite_column(frame: pd.DataFrame, label: str,
                          column: str) -> None:
    values = pd.to_numeric(frame[column], errors="raise")
    if not values.map(math.isfinite).all():
        raise ValueError(f"{label}: non-finite {column} values")


def dominant_crop_2023(crops_2023: pd.DataFrame) -> str:
    totals = (crops_2023.groupby("cdl_name", sort=False)["valid_pixels"]
              .sum().reset_index())
    totals = totals.sort_values(
        ["valid_pixels", "cdl_name"], ascending=[False, True], kind="stable")
    return str(totals.iloc[0]["cdl_name"])


def scene_date(scene: dict) -> str:
    try:
        return scene["selected_scene_datetime"].split("T", 1)[0]
    except (KeyError, AttributeError) as error:
        raise ValueError(
            "scene.json is missing selected_scene_datetime") from error


def build_sources(scene_id: str, scene_dt: str) -> dict:
    ndvi = {**BASE_SOURCES["ndvi"], "version": scene_id, "date": scene_dt}
    return {**BASE_SOURCES, "ndvi": ndvi}


def require_finite(payload: dict) -> None:
    bad = sorted(key for key in FINITE_KEYS
                 if not math.isfinite(float(payload[key])))
    if bad:
        raise ValueError("non-finite KPI values: " + ", ".join(bad))


def build_payload(root: Path = ROOT) -> dict:
    paths = require_inputs(root)

    summary = pd.read_csv(paths["field_summary"])
    if len(summary) != 1:
        raise ValueError("field_summary.csv must contain exactly one row")
    field_count = int(summary.loc[0, "field_count"])
    if field_count != FIELD_COUNT:
        raise ValueError(
            f"expected {FIELD_COUNT} fields, found {field_count}")
    if int(summary.loc[0, "duplicate_field_id_count"]) != 0:
        raise ValueError("field_summary.csv reports duplicate field ids")
    total_area_ha = float(summary.loc[0, "total_area_ha"])

    crops = pd.read_csv(paths["crops"])
    crops_2023 = crops.loc[crops["year"] == 2023]
    require_field_rows(crops_2023, "cdl_EPSG4326.csv 2023")
    require_finite_column(crops_2023, "cdl_EPSG4326.csv 2023",
                          "valid_pixels")
    dominant = dominant_crop_2023(crops_2023)

    ndvi = pd.read_csv(paths["ndvi"])
    require_field_rows(ndvi, "field_ndvi.csv")
    require_finite_column(ndvi, "field_ndvi.csv", "mean_ndvi")
    require_finite_column(ndvi, "field_ndvi.csv", "coverage_fraction")
    mean_ndvi = float(ndvi["mean_ndvi"].mean())
    ndvi_coverage_pct = float(ndvi["coverage_fraction"].mean()) * 100.0

    scene = json.loads(paths["scene"].read_text(encoding="utf-8"))
    scene_id = scene["selected_scene_id"]
    scene_dt = scene_date(scene)

    weather = json.loads(paths["weather"].read_text(encoding="utf-8"))
    t2m_anomaly = float(weather["t2m_anomaly_2023_c"])
    precip = float(weather["precip_2023_mm"])

    soil = json.loads(paths["soil"].read_text(encoding="utf-8"))
    if int(soil.get("field_count", -1)) != FIELD_COUNT:
        raise ValueError(
            f"soil summary: expected {FIELD_COUNT} fields, "
            f"found {soil.get('field_count')}")
    soil_metrics = soil["metrics"]
    soil_values = {key: float(soil_metrics[source]["mean"])
                   for key, source in SOIL_METRICS.items()}

    payload = {
        "field_count": field_count,
        "total_area_ha": total_area_ha,
        "dominant_crop_2023": dominant,
        "mean_ndvi": mean_ndvi,
        "ndvi_coverage_pct": ndvi_coverage_pct,
        "scene_date": scene_dt,
        "t2m_anomaly_2023_c": t2m_anomaly,
        "precip_2023_mm": precip,
        **soil_values,
        "sources": build_sources(scene_id, scene_dt),
    }
    require_finite(payload)
    return payload


def main() -> None:
    write_manifest(OUTPUT_PATH, build_payload(ROOT))


if __name__ == "__main__":
    main()
