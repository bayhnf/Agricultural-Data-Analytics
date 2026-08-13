"""Assignment 7: integrate crop, soil, and NDVI evidence per field."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
FIELDS_PATH = ROOT / "data/processed/assignment-02/fields_with_crops.geojson"
CDL_PATH = ROOT / "data/processed/assignment-02/cdl_EPSG4326.csv"
SOIL_OVERLAPS_PATH = (
    ROOT / "data/processed/assignment-04/field_soil_overlap.csv")
NDVI_PATH = ROOT / "data/processed/assignment-05/field_ndvi.csv"
OUTPUT_DIR = ROOT / "data/processed/assignment-07"
FIGURE_PATH = ROOT / "docs/assets/integrated_spatial_analysis.png"
FIELD_COUNT = 25
SQUARE_METRES_PER_HECTARE = 10000.0

INTEGRATED_COLUMNS = [
    "field_id",
    "crop_2023_name",
    "dominant_soil",
    "dominant_soil_name",
    "dominant_soil_mukey",
    "dominant_soil_overlap_area_ha",
    "mean_ndvi",
    "valid_pixel_count",
    "total_pixel_count",
    "ndvi_coverage_fraction",
]


def derive_dominant_soils(overlaps: pd.DataFrame) -> pd.DataFrame:
    """Select maximum overlap per field, then lexical mukey on ties."""
    work = overlaps.copy()
    missing = {
        "field_id", "mukey", "musym", "muname", "overlap_area_ha",
    } - set(work.columns)
    if missing:
        raise ValueError(
            "overlaps missing required columns: "
            + ", ".join(sorted(missing)))
    work["_mukey"] = work["mukey"].astype(str)
    selected = (
        work
        .sort_values(
            ["field_id", "overlap_area_ha", "_mukey"],
            ascending=[True, False, True],
            kind="stable",
        )
        .drop_duplicates("field_id", keep="first")
        .rename(columns={
            "musym": "dominant_soil",
            "muname": "dominant_soil_name",
            "mukey": "dominant_soil_mukey",
            "overlap_area_ha": "dominant_soil_overlap_area_ha",
        })
    )
    return selected[[
        "field_id",
        "dominant_soil",
        "dominant_soil_name",
        "dominant_soil_mukey",
        "dominant_soil_overlap_area_ha",
    ]].reset_index(drop=True)


REQUIRED_COLUMNS = {
    "fields": ("field_id",),
    "crops": ("field_id", "crop_2023_name"),
    "soils": ("field_id", "dominant_soil"),
    "ndvi": ("field_id", "mean_ndvi", "coverage_fraction"),
}


def _check_keys(name: str, frame: pd.DataFrame) -> None:
    missing = set(REQUIRED_COLUMNS[name]) - set(frame.columns)
    if missing:
        raise ValueError(
            f"{name} missing required columns: "
            + ", ".join(sorted(missing)))
    if frame["field_id"].duplicated().any():
        raise ValueError(f"{name} must have unique field_id values")


def integrate_fields(fields, crops, soils, ndvi):
    """Join one-row-per-field inputs while preserving null NDVI values."""
    geospatial = isinstance(fields, gpd.GeoDataFrame)
    for name, frame in (
        ("fields", fields),
        ("crops", crops),
        ("soils", soils),
        ("ndvi", ndvi),
    ):
        _check_keys(name, frame)

    field_keys = set(fields["field_id"])
    for name, frame in (
        ("crops", crops),
        ("soils", soils),
        ("ndvi", ndvi),
    ):
        if set(frame["field_id"]) != field_keys:
            raise ValueError(f"{name} field_id keys do not match fields")

    soils = soils.copy()
    for column in (
        "dominant_soil_name",
        "dominant_soil_mukey",
        "dominant_soil_overlap_area_ha",
    ):
        if column not in soils.columns:
            soils[column] = pd.NA

    ndvi = ndvi.rename(
        columns={"coverage_fraction": "ndvi_coverage_fraction"}).copy()
    for column in ("valid_pixel_count", "total_pixel_count"):
        if column not in ndvi.columns:
            ndvi[column] = pd.NA

    if geospatial:
        geometry = fields[["field_id", "geometry"]].copy()
        crs = fields.crs
    result = fields[["field_id"]]
    for frame in (crops, soils, ndvi):
        result = result.merge(
            frame, on="field_id", how="left", validate="one_to_one")
    result = (
        result[INTEGRATED_COLUMNS]
        .sort_values("field_id", kind="stable")
        .reset_index(drop=True)
    )
    if geospatial:
        result = gpd.GeoDataFrame(
            result.merge(geometry, on="field_id", how="left"),
            geometry="geometry",
            crs=crs,
        )
    return result


def build_integrated_dataset(
    fields,
    crop_history,
    soil_overlaps,
    ndvi,
):
    """Select 2023 crops, convert soil area to hectares, then integrate."""
    missing = {"field_id", "year", "cdl_name"} - set(crop_history.columns)
    if missing:
        raise ValueError(
            "crop_history missing required columns: "
            + ", ".join(sorted(missing)))
    crops_2023 = crop_history.loc[crop_history["year"] == 2023]
    if crops_2023["field_id"].duplicated().any():
        raise ValueError("crop_history must have unique 2023 field_id")
    if set(crops_2023["field_id"]) != set(fields["field_id"]):
        raise ValueError("2023 crop field_id keys must match fields")
    crops = (
        crops_2023[["field_id", "cdl_name"]]
        .rename(columns={"cdl_name": "crop_2023_name"})
    )

    overlaps = soil_overlaps.copy()
    missing = {
        "field_id", "mukey", "musym", "muname", "overlap_area_m2",
    } - set(overlaps.columns)
    if missing:
        raise ValueError(
            "soil_overlaps missing required columns: "
            + ", ".join(sorted(missing)))
    overlaps["overlap_area_ha"] = (
        overlaps["overlap_area_m2"] / SQUARE_METRES_PER_HECTARE)
    return integrate_fields(
        fields,
        crops,
        derive_dominant_soils(overlaps),
        ndvi,
    )


def _load_fields() -> gpd.GeoDataFrame:
    fields = gpd.read_file(FIELDS_PATH)
    if fields.crs is None:
        raise ValueError("fields must declare a CRS")
    if (
        len(fields) != FIELD_COUNT
        or fields["field_id"].nunique() != FIELD_COUNT
        or fields.geometry.isna().any()
        or fields.geometry.is_empty.any()
    ):
        raise ValueError(f"expected {FIELD_COUNT} unique non-empty fields")
    return fields


def _plot_integrated(integrated: gpd.GeoDataFrame) -> None:
    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(16, 5))
    mapped = integrated.to_crs(4326)
    mapped.plot(
        column="mean_ndvi",
        ax=axes[0],
        cmap="RdYlGn",
        vmin=-1.0,
        vmax=1.0,
        legend=True,
        legend_kwds={"label": "Mean NDVI 2023", "shrink": 0.7},
    )
    axes[0].set_title("Field-level mean NDVI (2023)")
    axes[0].set_axis_off()

    by_crop = (
        mapped.groupby("crop_2023_name")["mean_ndvi"]
        .mean()
        .sort_values()
    )
    by_crop.plot.bar(ax=axes[1], color="#4d7f3f", rot=0)
    axes[1].set_title("Mean NDVI by 2023 crop")
    axes[1].set_xlabel("2023 crop")
    axes[1].set_ylabel("Mean NDVI")

    by_soil = (
        mapped.groupby("dominant_soil")["mean_ndvi"]
        .mean()
        .sort_values()
    )
    by_soil.plot.bar(ax=axes[2], color="#7f5a3f", rot=90)
    axes[2].set_title("Mean NDVI by dominant soil")
    axes[2].set_xlabel("Dominant soil (musym)")
    axes[2].set_ylabel("Mean NDVI")
    axes[2].tick_params(axis="x", labelsize=7)

    figure.suptitle("Integrated field analysis (2023)")
    figure.text(
        0.5,
        0.015,
        "Descriptive comparisons only; they do not imply causation.",
        ha="center",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.96))
    figure.savefig(FIGURE_PATH, dpi=160)
    plt.close(figure)


def main() -> None:
    fields = _load_fields()
    crop_history = pd.read_csv(CDL_PATH)
    soil_overlaps = pd.read_csv(
        SOIL_OVERLAPS_PATH, dtype={"mukey": str, "musym": str})
    ndvi = pd.read_csv(NDVI_PATH)
    integrated = build_integrated_dataset(
        fields, crop_history, soil_overlaps, ndvi)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    integrated[INTEGRATED_COLUMNS].to_csv(
        OUTPUT_DIR / "integrated_field_summary.csv", index=False)
    integrated.to_crs(4326).to_file(
        OUTPUT_DIR / "integrated_fields.geojson", driver="GeoJSON")
    _plot_integrated(integrated)


if __name__ == "__main__":
    main()
