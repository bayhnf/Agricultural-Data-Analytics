"""Contract tests for the Task 11 dashboard data builder (slice A)."""

import json
import math
import pathlib
import tempfile
import unittest

import scripts.build_dashboard as build_dashboard


ROOT = pathlib.Path(__file__).resolve().parents[1]

KPI_KEYS = frozenset({
    "field_count",
    "total_area_ha",
    "dominant_crop_2023",
    "mean_ndvi",
    "ndvi_coverage_pct",
    "scene_date",
    "t2m_anomaly_2023_c",
    "precip_2023_mm",
    "mean_organic_matter_pct",
    "mean_ph",
    "mean_cec_cmol_kg",
    "mean_carbon_storage_mg_c_ha",
})
EXPECTED_KEYS = KPI_KEYS | {"sources"}
SOURCE_NAMES = frozenset({"fields", "crops", "ndvi", "weather", "soil",
                          "units"})
NUMERIC_KEYS = KPI_KEYS - {"dominant_crop_2023", "scene_date"}


def write_minimal_inputs(root: pathlib.Path) -> None:
    """Write all six synthetic Assignment 2-8 products under root."""
    base = root / "data/processed"
    (base / "assignment-02").mkdir(parents=True, exist_ok=True)
    (base / "assignment-05").mkdir(parents=True, exist_ok=True)
    (base / "assignment-06").mkdir(parents=True, exist_ok=True)
    (base / "assignment-08").mkdir(parents=True, exist_ok=True)

    (base / "assignment-02" / "field_summary.csv").write_text(
        "field_count,total_area_ha,mean_area_ha,median_area_ha,"
        "crop_record_count,missing_crop_record_count,"
        "duplicate_field_id_count\n25,100.0,4.0,4.0,100,0,0\n",
        encoding="utf-8")

    crop_rows = [
        "field_id,year,cdl_code,cdl_name,majority_fraction,"
        "coverage_fraction,valid_pixels,total_pixels",
    ]
    for index in range(1, 26):
        field_id = f"STORY-{index:02d}"
        name = "Corn" if index % 2 else "Soybeans"
        pixels = index * 10
        crop_rows.append(
            f"{field_id},2023,1,{name},0.9,1.0,{pixels},{pixels}")
    (base / "assignment-02" / "cdl_EPSG4326.csv").write_text(
        "\n".join(crop_rows) + "\n", encoding="utf-8")

    ndvi_rows = [
        "field_id,mean_ndvi,median_ndvi,valid_pixel_count,"
        "total_pixel_count,coverage_fraction",
    ]
    for index in range(1, 26):
        ndvi_rows.append(f"STORY-{index:02d},0.8,0.8,100,100,1.0")
    (base / "assignment-05" / "field_ndvi.csv").write_text(
        "\n".join(ndvi_rows) + "\n", encoding="utf-8")

    (base / "assignment-05" / "scene.json").write_text(
        json.dumps({
            "selected_scene_id": "S2B_15TVG_20230620_0_L2A",
            "selected_scene_datetime": "2023-06-20T17:12:11.504000Z",
        }) + "\n",
        encoding="utf-8")
    (base / "assignment-06" / "weather_summary.json").write_text(
        json.dumps({
            "precip_2023_mm": 627.62,
            "record_count": 12053,
            "t2m_anomaly_2023_c": 1.8,
        }) + "\n",
        encoding="utf-8")
    metrics = {}
    for name, unit in (
        ("organic_matter_pct", "%"),
        ("ph_h2o", "pH units"),
        ("cec_cmol_kg", "cmol(+)/kg"),
        ("carbon_storage_mg_c_ha", "Mg C/ha"),
    ):
        metrics[name] = {
            "mean": 1.0,
            "mean_coverage_fraction": 1.0,
            "median": 1.0,
            "non_null_fields": 25,
            "unit": unit,
        }
    (base / "assignment-08" / "soil_health_summary.json").write_text(
        json.dumps({"field_count": 25, "metrics": metrics},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


class DashboardDataTest(unittest.TestCase):
    def test_payload_has_exact_kpi_contract_and_is_deterministic(self):
        payload = build_dashboard.build_payload(ROOT)
        self.assertEqual(set(payload), EXPECTED_KEYS)
        self.assertEqual(payload["field_count"], 25)
        self.assertEqual(payload["scene_date"], "2023-06-20")
        self.assertEqual(payload["dominant_crop_2023"], "Corn")
        self.assertEqual(payload["ndvi_coverage_pct"], 100.0)
        for key in NUMERIC_KEYS:
            self.assertTrue(math.isfinite(float(payload[key])), key)
        self.assertEqual(set(payload["sources"]), SOURCE_NAMES)
        self.assertEqual(set(payload["sources"]["units"]) & KPI_KEYS,
                         KPI_KEYS)
        self.assertIn("Copernicus",
                      payload["sources"]["ndvi"]["license_note"])
        self.assertEqual(payload, build_dashboard.build_payload(ROOT))

    def test_main_writes_sorted_deterministic_json(self):
        build_dashboard.main()
        output = ROOT / "docs/data/dashboard.json"
        payload = build_dashboard.build_payload(ROOT)
        expected = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        self.assertEqual(output.read_text(encoding="utf-8"), expected)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")),
                         payload)

    def test_rejects_missing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                build_dashboard.build_payload(pathlib.Path(directory))

    def test_rejects_non_finite_kpi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            ndvi_path = (root / "data/processed/assignment-05"
                         / "field_ndvi.csv")
            lines = ndvi_path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace(",0.8,", ",NaN,", 1)
            ndvi_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_rejects_wrong_field_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            summary = (root / "data/processed/assignment-02"
                       / "field_summary.csv")
            summary.write_text("field_count,total_area_ha\n24,100.0\n",
                               encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_rejects_duplicate_field_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            ndvi_path = (root / "data/processed/assignment-05"
                         / "field_ndvi.csv")
            lines = ndvi_path.read_text(encoding="utf-8").splitlines()
            lines[-1] = lines[1]
            ndvi_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)


if __name__ == "__main__":
    unittest.main()
