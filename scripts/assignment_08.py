"""Assignment 8: SSURGO soil-health and carbon screening metrics."""

from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = (
    ROOT / "data/raw/ssurgo/wss_SSA_IA169_[2025-09-09].zip")
OVERLAP_PATH = (
    ROOT / "data/processed/assignment-04/field_soil_overlap.csv")
OUTPUT_DIR = ROOT / "data/processed/assignment-08"
FIGURE_PATH = ROOT / "docs/assets/soil_health_metrics.png"
DEPTH_LIMIT_CM = 30.0
FIELD_COUNT = 25

TABLE_FILES = {
    "mapunit": "IA169/tabular/mapunit.txt",
    "component": "IA169/tabular/comp.txt",
    "chorizon": "IA169/tabular/chorizon.txt",
}
TABLE_COLUMNS = {
    "mapunit": ("mukey", "musym", "muname"),
    "component": ("mukey", "cokey", "comppct_r", "compname"),
    "chorizon": (
        "cokey",
        "hzdept_r",
        "hzdepb_r",
        "om_r",
        "ph1to1h2o_r",
        "cec7_r",
        "dbthirdbar_r",
        "kwfact",
    ),
}
METRIC_SPECS = {
    "organic_matter_pct": ("om_r", "om_coverage_fraction"),
    "ph_h2o": ("ph1to1h2o_r", "ph_coverage_fraction"),
    "cec_cmol_kg": ("cec7_r", "cec_coverage_fraction"),
    "erosion_k_factor": ("kwfact", "erosion_coverage_fraction"),
    "carbon_storage_mg_c_ha": (None, "carbon_coverage_fraction"),
}
SOIL_COLUMNS = [
    "field_id",
    "organic_matter_pct",
    "ph_h2o",
    "cec_cmol_kg",
    "erosion_k_factor",
    "carbon_storage_mg_c_ha",
    "soil_coverage_fraction",
    "om_coverage_fraction",
    "ph_coverage_fraction",
    "cec_coverage_fraction",
    "erosion_coverage_fraction",
    "carbon_coverage_fraction",
]


def horizon_overlap_cm(
    top_cm: float,
    bottom_cm: float,
    limit_cm: float = DEPTH_LIMIT_CM,
) -> float:
    """Return horizon thickness intersecting the interval 0..limit_cm."""
    top, bottom, limit = map(float, (top_cm, bottom_cm, limit_cm))
    if not all(math.isfinite(value) for value in (top, bottom, limit)):
        raise ValueError("horizon depths and limit must be finite")
    if limit <= 0:
        raise ValueError("depth limit must be positive")
    if bottom < top:
        raise ValueError("horizon bottom must not be above top")
    return max(0.0, min(bottom, limit) - max(top, 0.0))


def carbon_stock_mg_ha(
    organic_matter_percent: float,
    bulk_density_g_cm3: float,
    thickness_cm: float,
) -> float:
    """Estimate carbon stock from OM, bulk density, and layer thickness."""
    organic_matter = float(organic_matter_percent)
    bulk_density = float(bulk_density_g_cm3)
    thickness = float(thickness_cm)
    if not all(math.isfinite(value)
               for value in (organic_matter, bulk_density, thickness)):
        raise ValueError("carbon inputs must be finite")
    if organic_matter < 0 or bulk_density <= 0 or thickness < 0:
        raise ValueError("carbon inputs must be non-negative with positive "
                         "bulk density")
    return bulk_density * thickness * (organic_matter / 1.724)


def weighted_ph(values) -> float:
    """Average pH in hydrogen-ion concentration space."""
    numerator = denominator = 0.0
    for ph_value, weight_value in values:
        ph, weight = float(ph_value), float(weight_value)
        if not math.isfinite(ph) or not math.isfinite(weight):
            raise ValueError("pH values and weights must be finite")
        if not 0 < ph <= 14:
            raise ValueError("pH must be in (0, 14]")
        if weight < 0:
            raise ValueError("pH weights must be non-negative")
        if weight:
            numerator += weight * (10 ** -ph)
            denominator += weight
    if denominator == 0:
        raise ValueError("pH requires at least one positive weight")
    return -math.log10(numerator / denominator)


def parse_column_positions(
    mstabcol_text: str,
    table_name: str,
    required_columns,
) -> tuple[dict[str, int], int]:
    """Resolve selected SSURGO column indexes and full row width."""
    columns: dict[int, str] = {}
    for row in csv.reader(io.StringIO(mstabcol_text), delimiter="|"):
        if len(row) < 3 or row[0].strip() != table_name:
            continue
        try:
            ordinal = int(row[1].strip())
        except ValueError:
            raise ValueError(
                f"invalid {table_name} column ordinal") from None
        name = row[2].strip()
        if ordinal in columns and columns[ordinal] != name:
            raise ValueError(
                f"conflicting {table_name} column {ordinal}")
        columns[ordinal] = name
    if not columns:
        raise ValueError(f"no {table_name} metadata in mstabcol.txt")
    if set(columns) != set(range(1, max(columns) + 1)):
        raise ValueError(f"{table_name} column ordinals are not contiguous")
    missing = set(required_columns) - set(columns.values())
    if missing:
        raise ValueError(
            f"{table_name} columns missing: " + ", ".join(sorted(missing)))
    indexes = {
        name: ordinal - 1
        for ordinal, name in columns.items()
        if name in required_columns
    }
    return indexes, max(columns)


def read_selected_table(lines, positions, width: int) -> pd.DataFrame:
    """Read selected pipe-delimited columns while validating full row width."""
    rows = []
    for number, row in enumerate(csv.reader(lines, delimiter="|"), start=1):
        if len(row) != width:
            raise ValueError(
                f"SSURGO row {number} has {len(row)} fields, expected {width}")
        rows.append({
            name: row[index].strip()
            for name, index in positions.items()
        })
    if not rows:
        raise ValueError("SSURGO table contains no rows")
    return pd.DataFrame(rows, columns=list(positions))


def _required(frame: pd.DataFrame, name: str, columns) -> pd.DataFrame:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(
            f"{name} missing required columns: "
            + ", ".join(sorted(missing)))
    return frame.loc[:, columns].copy()


def _identifiers(
    frame: pd.DataFrame,
    name: str,
    columns,
    allow_empty=(),
) -> None:
    for column in columns:
        frame[column] = frame[column].astype("string").str.strip()
        invalid = frame[column].isna()
        if column not in allow_empty:
            invalid |= frame[column].eq("")
        if invalid.any():
            raise ValueError(f"{name} has empty {column}")


def _numbers(frame: pd.DataFrame, name: str, columns) -> None:
    for column in columns:
        raw = frame[column].astype("string").str.strip()
        parsed = pd.to_numeric(raw.mask(raw.eq("")), errors="coerce")
        invalid = raw.notna() & raw.ne("") & parsed.isna()
        if invalid.any():
            raise ValueError(f"{name} has invalid numeric {column}")
        frame[column] = parsed.astype(float)


def _component_metrics(horizons: pd.DataFrame) -> dict[str, float]:
    weighted = {
        "organic_matter_pct": [],
        "ph_h2o": [],
        "cec_cmol_kg": [],
        "erosion_k_factor": [],
    }
    carbon = 0.0
    has_carbon = False
    for row in horizons.itertuples(index=False):
        if pd.isna(row.hzdept_r) or pd.isna(row.hzdepb_r):
            continue
        thickness = horizon_overlap_cm(row.hzdept_r, row.hzdepb_r)
        if thickness == 0:
            continue
        for metric, source in (
            ("organic_matter_pct", "om_r"),
            ("ph_h2o", "ph1to1h2o_r"),
            ("cec_cmol_kg", "cec7_r"),
            ("erosion_k_factor", "kwfact"),
        ):
            value = getattr(row, source)
            if pd.notna(value):
                weighted[metric].append((float(value), thickness))
        if pd.notna(row.om_r) and pd.notna(row.dbthirdbar_r):
            carbon += carbon_stock_mg_ha(
                row.om_r, row.dbthirdbar_r, thickness)
            has_carbon = True
    result = {}
    for metric, values in weighted.items():
        if not values:
            result[metric] = math.nan
        elif metric == "ph_h2o":
            result[metric] = weighted_ph(values)
        else:
            total_weight = sum(weight for _, weight in values)
            result[metric] = (
                sum(value * weight for value, weight in values)
                / total_weight
            )
    result["carbon_storage_mg_c_ha"] = carbon if has_carbon else math.nan
    return result


def aggregate_soil_metrics(
    components: pd.DataFrame,
    horizons: pd.DataFrame,
    overlaps: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate 0-30 cm SSURGO properties to one row per field."""
    components = _required(
        components,
        "components",
        ("mukey", "cokey", "comppct_r", "compname"),
    )
    horizons = _required(
        horizons,
        "horizons",
        (
            "cokey",
            "hzdept_r",
            "hzdepb_r",
            "om_r",
            "ph1to1h2o_r",
            "cec7_r",
            "dbthirdbar_r",
            "kwfact",
        ),
    )
    overlaps = _required(
        overlaps, "overlaps", ("field_id", "mukey", "field_fraction"))
    _identifiers(components, "components", ("mukey", "cokey", "compname"))
    _identifiers(horizons, "horizons", ("cokey",))
    _identifiers(overlaps, "overlaps", ("field_id", "mukey"),
                 allow_empty=("mukey",))
    _numbers(components, "components", ("comppct_r",))
    _numbers(
        horizons,
        "horizons",
        (
            "hzdept_r",
            "hzdepb_r",
            "om_r",
            "ph1to1h2o_r",
            "cec7_r",
            "dbthirdbar_r",
            "kwfact",
        ),
    )
    _numbers(overlaps, "overlaps", ("field_fraction",))

    if components["cokey"].duplicated().any():
        raise ValueError("duplicate component cokey")
    if horizons.duplicated().any():
        raise ValueError("duplicate horizon rows")
    if overlaps.duplicated(["field_id", "mukey"]).any():
        raise ValueError("duplicate field/mapunit overlap")
    if components["comppct_r"].dropna().lt(0).any():
        raise ValueError("component percentages must be non-negative")
    if overlaps["field_fraction"].isna().any() or (
        ~overlaps["field_fraction"].between(0, 1)
    ).any():
        raise ValueError("field fractions must be between 0 and 1")
    if (horizons["om_r"].dropna() < 0).any():
        raise ValueError("organic matter must be non-negative")
    if (~horizons["ph1to1h2o_r"].dropna().between(0, 14)).any():
        raise ValueError("pH must be between 0 and 14")
    if (horizons["cec7_r"].dropna() < 0).any():
        raise ValueError("CEC must be non-negative")
    if (horizons["dbthirdbar_r"].dropna() <= 0).any():
        raise ValueError("bulk density must be positive")
    if (horizons["kwfact"].dropna() < 0).any():
        raise ValueError("erosion K-factor must be non-negative")
    orphan_horizons = set(horizons["cokey"]) - set(components["cokey"])
    if orphan_horizons:
        raise ValueError("horizons reference unknown components")

    component_values = []
    horizon_groups = {
        cokey: group
        for cokey, group in horizons.groupby("cokey", sort=False)
    }
    for component in components.itertuples(index=False):
        component_horizons = horizon_groups.get(
            component.cokey, horizons.iloc[0:0])
        metrics = _component_metrics(component_horizons)
        has_profile = any(
            pd.notna(row.hzdept_r)
            and pd.notna(row.hzdepb_r)
            and horizon_overlap_cm(row.hzdept_r, row.hzdepb_r) > 0
            for row in component_horizons.itertuples(index=False)
        )
        component_values.append({
            "mukey": component.mukey,
            "cokey": component.cokey,
            "comppct_r": component.comppct_r,
            "has_profile": has_profile,
            **metrics,
        })
    component_values = pd.DataFrame(component_values)
    soil_mapunit_keys = set(
        component_values.loc[
            component_values["comppct_r"].fillna(0).gt(0)
            & component_values["has_profile"],
            "mukey",
        ]
    )

    mapunit_metrics = {}
    for mukey, group in component_values.groupby("mukey", sort=False):
        positive = group.loc[group["comppct_r"].fillna(0).gt(0)].copy()
        total_pct = positive["comppct_r"].sum()
        metrics = {}
        if total_pct > 0:
            for metric in METRIC_SPECS:
                available = positive.loc[positive[metric].notna()]
                available_pct = available["comppct_r"].sum()
                if available_pct == 0:
                    metrics[metric] = math.nan
                    metrics[f"{metric}_coverage"] = 0.0
                    continue
                if metric == "ph_h2o":
                    metrics[metric] = weighted_ph(
                        zip(available[metric], available["comppct_r"]))
                else:
                    metrics[metric] = (
                        (available[metric] * available["comppct_r"]).sum()
                        / available_pct
                    )
                metrics[f"{metric}_coverage"] = available_pct / total_pct
        mapunit_metrics[mukey] = metrics

    rows = []
    for field_id, group in overlaps.groupby("field_id", sort=False):
        fraction_sum = group["field_fraction"].sum()
        if fraction_sum > 1.000001:
            raise ValueError(f"{field_id} soil fractions exceed 1")
        soil_fraction = group.loc[
            group["mukey"].isin(soil_mapunit_keys), "field_fraction"
        ].sum()
        row = {
            "field_id": field_id,
            "soil_coverage_fraction": min(float(soil_fraction), 1.0),
        }
        for metric, (_, coverage_column) in METRIC_SPECS.items():
            values = []
            for overlap in group.itertuples(index=False):
                mapunit = mapunit_metrics.get(overlap.mukey, {})
                value = mapunit.get(metric, math.nan)
                coverage = mapunit.get(f"{metric}_coverage", 0.0)
                weight = float(overlap.field_fraction) * coverage
                if weight > 0 and pd.notna(value):
                    values.append((float(value), weight))
            field_coverage = sum(weight for _, weight in values)
            row[coverage_column] = min(field_coverage, 1.0)
            if not values:
                row[metric] = math.nan
            elif metric == "ph_h2o":
                row[metric] = weighted_ph(values)
            else:
                row[metric] = (
                    sum(value * weight for value, weight in values)
                    / field_coverage
                )
        rows.append(row)
    return (
        pd.DataFrame(rows, columns=SOIL_COLUMNS)
        .sort_values("field_id", kind="stable")
        .reset_index(drop=True)
    )


def load_ssurgo_tables(archive_path: Path) -> dict[str, pd.DataFrame]:
    """Read only the required columns from three SSURGO tabular files."""
    with zipfile.ZipFile(archive_path) as archive:
        metadata = archive.read(
            "IA169/tabular/mstabcol.txt").decode("utf-8")
        tables = {}
        for table_name, member in TABLE_FILES.items():
            positions, width = parse_column_positions(
                metadata, table_name, TABLE_COLUMNS[table_name])
            with archive.open(member) as raw:
                lines = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                tables[table_name] = read_selected_table(
                    lines, positions, width)
        return tables


def _build_summary(rows: pd.DataFrame) -> dict:
    units = {
        "organic_matter_pct": "%",
        "ph_h2o": "pH units",
        "cec_cmol_kg": "cmol(+)/kg",
        "erosion_k_factor": "dimensionless K factor",
        "carbon_storage_mg_c_ha": "Mg C/ha",
    }
    metrics = {}
    for metric, (_, coverage_column) in METRIC_SPECS.items():
        values = rows[metric].dropna()
        metrics[metric] = {
            "unit": units[metric],
            "mean": float(values.mean()) if not values.empty else None,
            "median": float(values.median()) if not values.empty else None,
            "non_null_fields": int(values.size),
            "mean_coverage_fraction": float(rows[coverage_column].mean()),
        }
    return {
        "field_count": int(len(rows)),
        "depth_limit_cm": int(DEPTH_LIMIT_CM),
        "source": "USDA NRCS SSURGO IA169 snapshot 2025-09-09",
        "metrics": metrics,
        "interpretation": (
            "Field values are soil screening estimates from generalized "
            "SSURGO mapunit, component, and horizon data; they are not a "
            "farm recommendation."
        ),
    }


def _plot_metrics(rows: pd.DataFrame) -> None:
    specs = [
        ("organic_matter_pct", "Organic matter (%)", "#4d7f3f"),
        ("ph_h2o", "pH (1:1 H2O)", "#577590"),
        ("cec_cmol_kg", "CEC (cmol(+)/kg)", "#6d597a"),
        ("erosion_k_factor", "Erosion K-factor", "#bc6c25"),
        ("carbon_storage_mg_c_ha", "Carbon stock (Mg C/ha)", "#386641"),
    ]
    figure, axes = plt.subplots(3, 2, figsize=(14, 11))
    positions = range(len(rows))
    for axis, (column, title, color) in zip(axes.flat, specs):
        axis.bar(positions, rows[column], color=color)
        axis.set_title(title)
        axis.set_xticks(list(positions))
        axis.set_xticklabels(rows["field_id"], rotation=90, fontsize=6)
        axis.set_xlabel("Field")
        axis.set_ylabel(title)
        axis.grid(axis="y", alpha=0.25)
    axes.flat[-1].axis("off")
    figure.suptitle("Top 30 cm soil health screening metrics")
    figure.text(
        0.5,
        0.01,
        "SSURGO screening estimates; not a farm recommendation.",
        ha="center",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.97))
    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURE_PATH, dpi=160)
    plt.close(figure)


def main() -> None:
    if not ARCHIVE_PATH.is_file():
        raise FileNotFoundError(ARCHIVE_PATH)
    tables = load_ssurgo_tables(ARCHIVE_PATH)
    overlaps = pd.read_csv(OVERLAP_PATH, dtype={"mukey": str})
    mapunits = tables["mapunit"]
    _identifiers(mapunits, "mapunits", ("mukey", "musym", "muname"))
    if mapunits["mukey"].duplicated().any():
        raise ValueError("duplicate mapunit mukey")
    missing_mapunits = set(overlaps["mukey"].dropna().astype(str)) - set(
        mapunits["mukey"])
    if missing_mapunits:
        raise ValueError(
            "overlaps reference unknown mapunits: "
            + ", ".join(sorted(missing_mapunits)))

    rows = aggregate_soil_metrics(
        tables["component"],
        tables["chorizon"],
        overlaps,
    )
    if len(rows) != FIELD_COUNT or rows["field_id"].nunique() != FIELD_COUNT:
        raise ValueError(f"expected {FIELD_COUNT} unique fields")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.to_csv(OUTPUT_DIR / "soil_health_by_field.csv", index=False)
    (OUTPUT_DIR / "soil_health_summary.json").write_text(
        json.dumps(_build_summary(rows), indent=2, sort_keys=True) + "\n")
    _plot_metrics(rows)


if __name__ == "__main__":
    main()
