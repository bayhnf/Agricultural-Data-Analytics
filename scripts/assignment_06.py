"""Assignment 6: NASA POWER weather trends and anomalies."""

from __future__ import annotations

import json
import math
import numbers
import os
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd
import requests

from scripts.common import sha256_file, write_manifest

matplotlib.use("Agg")
from matplotlib import pyplot as plt

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMETERS = ("T2M", "PRECTOTCORR")
START_DATE = "19910101"
END_DATE = "20231231"
EXPECTED_DAYS = 12053
FILL_VALUE = -999.0
FULL_START = pd.Timestamp("1991-01-01")
FULL_END = pd.Timestamp("2023-12-31")

ROOT = Path(__file__).resolve().parents[1]
FIELDS_PATH = ROOT / "data/processed/assignment-02/fields_EPSG4326.geojson"
RAW_CACHE_PATH = ROOT / "data/raw/nasa_power/nasa_power_1991_2023.json"
OUTPUT_DIR = ROOT / "data/processed/assignment-06"
PROVENANCE_PATH = ROOT / "data/provenance/nasa_power_1991_2023.json"
FIGURE_PATH = ROOT / "docs/assets/weather_trends.png"


def power_request_params(longitude: float, latitude: float) -> dict:
    return {
        "parameters": ",".join(POWER_PARAMETERS),
        "community": "AG",
        "longitude": longitude,
        "latitude": latitude,
        "start": START_DATE,
        "end": END_DATE,
        "format": "JSON",
    }


def _parse_date_key(key) -> datetime:
    if not isinstance(key, str) or len(key) != 8 or not key.isdigit():
        raise ValueError(f"date keys must be YYYYMMDD strings, got {key!r}")
    try:
        return datetime.strptime(key, "%Y%m%d")
    except ValueError:
        raise ValueError(f"invalid date key {key!r}") from None


def _value(value, *, precipitation: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("values must be finite numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("values must be finite numeric")
    if number == FILL_VALUE:
        return float("nan")
    if precipitation and number < 0:
        raise ValueError("negative precipitation values are invalid")
    return number


def parse_power_daily(payload: dict) -> pd.DataFrame:
    """Validate a NASA POWER response and return sorted daily values."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    properties = payload.get("properties")
    parameters = (
        properties.get("parameter")
        if isinstance(properties, dict)
        else None
    )
    if not isinstance(parameters, dict):
        raise ValueError("payload must contain properties.parameter")
    missing = [
        name for name in POWER_PARAMETERS
        if not isinstance(parameters.get(name), dict)
    ]
    if missing:
        raise ValueError(
            "payload is missing POWER parameter(s): " + ", ".join(missing))

    temperature = parameters["T2M"]
    precipitation = parameters["PRECTOTCORR"]
    if set(temperature) != set(precipitation):
        raise ValueError("T2M and PRECTOTCORR date keys must match")
    keys = list(temperature)
    if not keys:
        raise ValueError("payload contains no daily records")
    for key in keys:
        _parse_date_key(key)

    frame = pd.DataFrame({
        "date": pd.to_datetime(keys, format="%Y%m%d"),
        "t2m_c": [_value(temperature[key]) for key in keys],
        "precip_mm": [
            _value(precipitation[key], precipitation=True) for key in keys
        ],
    }).sort_values("date", kind="stable").reset_index(drop=True)
    if (frame["date"].diff().iloc[1:] != pd.Timedelta(days=1)).any():
        raise ValueError("date keys must be unique and continuous")
    return frame


def _validate_full_period(daily: pd.DataFrame) -> None:
    if len(daily) != EXPECTED_DAYS:
        raise ValueError(
            f"expected exactly {EXPECTED_DAYS:,} daily records, "
            f"found {len(daily)}")
    if daily["date"].min() != FULL_START:
        raise ValueError("full period must start on 1991-01-01")
    if daily["date"].max() != FULL_END:
        raise ValueError("full period must end on 2023-12-31")


def analyze_weather(daily: pd.DataFrame) -> pd.DataFrame:
    """Add centered rolling temperature, baseline, and 2023 anomaly."""
    result = daily.copy().reset_index(drop=True)
    result["t2m_7d_c"] = result["t2m_c"].rolling(
        7, center=True, min_periods=7).mean()
    result["day_of_year"] = pd.to_datetime(
        "2000-" + result["date"].dt.strftime("%m-%d")).dt.dayofyear
    years = result["date"].dt.year
    baseline = (
        result.loc[years.between(1991, 2020)]
        .groupby("day_of_year")["t2m_c"]
        .mean()
    )
    result["baseline_t2m_c"] = result["day_of_year"].map(baseline)
    result["t2m_anomaly_c"] = (
        result["t2m_c"] - result["baseline_t2m_c"])
    result.loc[years != 2023, "t2m_anomaly_c"] = float("nan")
    return result[[
        "date", "t2m_c", "precip_mm", "t2m_7d_c",
        "day_of_year", "baseline_t2m_c", "t2m_anomaly_c",
    ]]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_weather_analysis(payload: dict, output_dir: Path) -> pd.DataFrame:
    """Write canonical daily and summary products for the full period."""
    daily = parse_power_daily(payload)
    _validate_full_period(daily)
    result = analyze_weather(daily)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "weather_daily.csv", index=False)
    year_2023 = result.loc[result["date"].dt.year == 2023]
    _write_json(output_dir / "weather_summary.json", {
        "record_count": int(len(result)),
        "t2m_anomaly_2023_c":
            float(year_2023["t2m_anomaly_c"].mean()),
        "precip_2023_mm": float(year_2023["precip_mm"].sum()),
    })
    return result


def fetch_power_daily(
    longitude: float,
    latitude: float,
    cache_path: Path = RAW_CACHE_PATH,
) -> tuple[dict, str, bool]:
    """Fetch one complete response or reuse a validated ignored cache."""
    cache_path = Path(cache_path)
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            _validate_full_period(parse_power_daily(payload))
        except ValueError:
            cache_path.unlink(missing_ok=True)
        else:
            retrieved = datetime.fromtimestamp(
                cache_path.stat().st_mtime, tz=timezone.utc).isoformat()
            return payload, retrieved, True

    response = requests.get(
        POWER_URL,
        params=power_request_params(longitude, latitude),
        timeout=(30, 300),
    )
    response.raise_for_status()
    payload = response.json()
    _validate_full_period(parse_power_daily(payload))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(response.text, encoding="utf-8")
    os.replace(temporary, cache_path)
    retrieved = datetime.fromtimestamp(
        cache_path.stat().st_mtime, tz=timezone.utc).isoformat()
    return payload, retrieved, False


def _load_fields(path: Path = FIELDS_PATH) -> gpd.GeoDataFrame:
    fields = gpd.read_file(path)
    if len(fields) != 25 or fields["field_id"].nunique() != 25:
        raise ValueError("expected exactly 25 unique selected fields")
    if fields.crs is None or fields.crs.to_epsg() != 4326:
        raise ValueError("selected fields must use EPSG:4326")
    if fields.geometry.isna().any() or fields.geometry.is_empty.any():
        raise ValueError("selected fields contain missing or empty geometry")
    return fields


def _payload_units(payload: dict) -> dict[str, str]:
    metadata = payload.get("parameters")
    if not isinstance(metadata, dict):
        return {}
    return {
        name: details["units"]
        for name, details in metadata.items()
        if isinstance(details, dict) and isinstance(details.get("units"), str)
    }


def plot_weather_trends(daily: pd.DataFrame, path: Path) -> None:
    """Render temperature, precipitation, and 2023 anomaly panels."""
    figure, axes = plt.subplots(3, 1, figsize=(11, 13))
    axes[0].plot(
        daily["date"], daily["t2m_c"],
        color="#1f77b4", linewidth=0.6, label="Daily temperature",
    )
    axes[0].plot(
        daily["date"], daily["t2m_7d_c"],
        color="#d62728", linewidth=1.4, label="Centered 7-day mean",
    )
    axes[0].set_ylabel("Temperature (°C)")
    axes[0].legend(loc="upper right")
    axes[0].set_title(
        "NASA POWER gridded assimilated estimates, "
        "Story County, Iowa (1991–2023)")
    axes[1].plot(
        daily["date"], daily["precip_mm"],
        color="#2ca02c", linewidth=0.5,
    )
    axes[1].set_ylabel("Precipitation (mm/day)")
    anomaly = daily.loc[daily["t2m_anomaly_c"].notna()]
    axes[2].plot(
        anomaly["date"], anomaly["t2m_anomaly_c"],
        color="#9467bd", linewidth=0.8,
    )
    axes[2].axhline(0.0, color="black", linewidth=0.8)
    axes[2].set_ylabel("2023 anomaly (°C)")
    axes[2].set_xlabel("Date")
    figure.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main() -> None:
    fields = _load_fields()
    centroid = fields.geometry.union_all().centroid
    longitude = round(float(centroid.x), 6)
    latitude = round(float(centroid.y), 6)
    payload, retrieved, _ = fetch_power_daily(longitude, latitude)
    result = build_weather_analysis(payload, OUTPUT_DIR)
    plot_weather_trends(result, FIGURE_PATH)

    request = power_request_params(longitude, latitude)
    request["parameters"] = list(POWER_PARAMETERS)
    manifest = {
        "dataset": "nasa_power_weather",
        "source_organization": "NASA Langley Research Center",
        "source_name": "NASA POWER daily point data (T2M, PRECTOTCORR)",
        "source_urls": [POWER_URL],
        "retrieved_utc": retrieved,
        "source_version": "POWER daily point API",
        "sha256": {
            str(RAW_CACHE_PATH.relative_to(ROOT)):
                sha256_file(RAW_CACHE_PATH)
        },
        "source_crs": "EPSG:4326",
        "output_crs": "EPSG:4326",
        "producer": "scripts/assignment_06.py",
        "request": request,
        "counts": {
            "daily_rows": int(len(result)),
            "anomaly_rows_2023":
                int(result["t2m_anomaly_c"].notna().sum()),
            "fields": 25,
        },
        "license_note":
            "NASA POWER T2M and PRECTOTCORR are gridded assimilated "
            "estimates provided by the NASA Langley Research Center POWER "
            "Project, not station observations.",
    }
    units = _payload_units(payload)
    if units:
        manifest["units"] = units
    write_manifest(PROVENANCE_PATH, manifest)


if __name__ == "__main__":
    main()
