import json
import math
import pathlib
import unittest

import pandas as pd

from scripts.assignment_08 import (
    SOIL_COLUMNS,
    aggregate_soil_metrics,
    carbon_stock_mg_ha,
    horizon_overlap_cm,
    parse_column_positions,
    read_selected_table,
    weighted_ph,
)


ROOT = pathlib.Path(__file__).parents[1]


def components_frame(*rows):
    return pd.DataFrame(
        rows, columns=["mukey", "cokey", "comppct_r", "compname"])


def horizons_frame(*rows):
    return pd.DataFrame(
        rows,
        columns=[
            "cokey",
            "hzdept_r",
            "hzdepb_r",
            "om_r",
            "ph1to1h2o_r",
            "cec7_r",
            "dbthirdbar_r",
            "kwfact",
        ],
    )


def overlaps_frame(*rows):
    return pd.DataFrame(
        rows, columns=["field_id", "mukey", "field_fraction"])


class SoilMetricTest(unittest.TestCase):
    def test_clips_horizon_to_top_30_cm(self):
        self.assertEqual(horizon_overlap_cm(10, 40), 20)
        self.assertEqual(horizon_overlap_cm(35, 60), 0)
        self.assertEqual(horizon_overlap_cm(-5, 10), 10)

    def test_rejects_inverted_horizon(self):
        with self.assertRaisesRegex(ValueError, "bottom"):
            horizon_overlap_cm(20, 10)

    def test_carbon_stock_uses_om_to_soc_conversion(self):
        # 3.448% OM -> 2% SOC; 1.3 g/cm3; 30 cm -> 78 Mg C/ha
        self.assertAlmostEqual(carbon_stock_mg_ha(3.448, 1.3, 30), 78.0)

    def test_weighted_ph_averages_hydrogen_concentration(self):
        result = weighted_ph([(6.0, 1.0), (7.0, 1.0)])
        self.assertAlmostEqual(result, -math.log10((1e-6 + 1e-7) / 2))


class TableParsingTest(unittest.TestCase):
    METADATA = (
        '"component"|1|"mukey"|"x"|"Mapunit"|"String"\n'
        '"component"|2|"cokey"|"x"|"Component"|"String"\n'
        '"component"|3|"comppct_r"|"x"|"Percent"|"Integer"\n'
        '"component"|4|"compname"|"x"|"Name"|"String"\n'
        '"chorizon"|1|"cokey"|"x"|"Component"|"String"\n'
    )

    def test_resolves_required_positions_from_metadata(self):
        positions, width = parse_column_positions(
            self.METADATA,
            "component",
            ("mukey", "cokey", "comppct_r", "compname"),
        )
        self.assertEqual(
            positions,
            {"mukey": 0, "cokey": 1, "comppct_r": 2, "compname": 3},
        )
        self.assertEqual(width, 4)

    def test_reads_only_selected_columns_and_validates_width(self):
        positions = {"mukey": 0, "compname": 3}
        frame = read_selected_table(
            ["411|c1|80|Clarion\n"], positions, width=4)
        self.assertEqual(
            frame.to_dict("records"),
            [{"mukey": "411", "compname": "Clarion"}],
        )
        with self.assertRaisesRegex(ValueError, "expected 4"):
            read_selected_table(["411|c1|80\n"], positions, width=4)


class SoilAggregationTest(unittest.TestCase):
    def test_normalizes_component_and_field_weights(self):
        components = components_frame(
            ("M1", "A", 80, "major"),
            ("M1", "B", 20, "minor"),
            ("M2", "C", 100, "other"),
        )
        horizons = horizons_frame(
            ("A", 0, 30, 4.0, 6.0, 10.0, 1.3, 0.2),
            ("B", 0, 30, 2.0, 7.0, 20.0, 1.2, 0.4),
            ("C", 0, 30, 2.0, 7.0, 30.0, 1.2, 0.3),
        )
        result = aggregate_soil_metrics(
            components,
            horizons,
            overlaps_frame(("F1", "M1", 0.6), ("F1", "M2", 0.4)),
        )
        self.assertAlmostEqual(result.loc[0, "organic_matter_pct"], 2.96)
        self.assertAlmostEqual(result.loc[0, "ph_h2o"], 6.274088367704951)
        self.assertAlmostEqual(result.loc[0, "soil_coverage_fraction"], 1.0)
        self.assertAlmostEqual(result.loc[0, "om_coverage_fraction"], 1.0)

    def test_carbon_sums_horizons_vertically(self):
        result = aggregate_soil_metrics(
            components_frame(("M1", "A", 100, "soil")),
            horizons_frame(
                ("A", 0, 15, 3.448, 6.0, 10.0, 1.3, 0.2),
                ("A", 15, 30, 3.448, 6.0, 10.0, 1.3, 0.2),
            ),
            overlaps_frame(("F1", "M1", 1.0)),
        )
        self.assertAlmostEqual(
            result.loc[0, "carbon_storage_mg_c_ha"], 78.0)

    def test_missing_values_are_not_zero_filled_and_coverage_is_separate(self):
        result = aggregate_soil_metrics(
            components_frame(
                ("M1", "A", 50, "organic"),
                ("M1", "B", 50, "ph-only"),
            ),
            horizons_frame(
                ("A", 0, 30, 4.0, None, None, None, None),
                ("B", 0, 30, None, 7.0, 20.0, None, 0.3),
            ),
            overlaps_frame(
                ("F1", "M1", 0.8),
                ("F1", "WATER", 0.2),
            ),
        )
        self.assertAlmostEqual(result.loc[0, "organic_matter_pct"], 4.0)
        self.assertAlmostEqual(result.loc[0, "ph_h2o"], 7.0)
        self.assertAlmostEqual(result.loc[0, "soil_coverage_fraction"], 1.0)
        self.assertAlmostEqual(result.loc[0, "om_coverage_fraction"], 0.4)
        self.assertAlmostEqual(result.loc[0, "ph_coverage_fraction"], 0.4)
        self.assertAlmostEqual(result.loc[0, "cec_coverage_fraction"], 0.4)
        self.assertAlmostEqual(
            result.loc[0, "erosion_coverage_fraction"], 0.4)
        self.assertEqual(result.loc[0, "carbon_coverage_fraction"], 0.0)
        self.assertTrue(
            pd.isna(result.loc[0, "carbon_storage_mg_c_ha"]))

    def test_water_only_field_is_retained_with_null_metrics(self):
        result = aggregate_soil_metrics(
            components_frame(("M1", "A", 100, "soil")),
            horizons_frame(
                ("A", 0, 30, 4.0, 6.0, 10.0, 1.3, 0.2)),
            overlaps_frame(("F2", "WATER", 1.0)),
        )
        self.assertEqual(result["field_id"].tolist(), ["F2"])
        self.assertAlmostEqual(result.loc[0, "soil_coverage_fraction"], 1.0)
        for metric in (
            "organic_matter_pct",
            "ph_h2o",
            "cec_cmol_kg",
            "erosion_k_factor",
            "carbon_storage_mg_c_ha",
        ):
            self.assertTrue(pd.isna(result.loc[0, metric]))

    def test_rejects_duplicate_field_mapunit_overlap(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            aggregate_soil_metrics(
                components_frame(("M1", "A", 100, "soil")),
                horizons_frame(
                    ("A", 0, 30, 4.0, 6.0, 10.0, 1.3, 0.2)),
                overlaps_frame(
                    ("F1", "M1", 0.5),
                    ("F1", "M1", 0.5),
                ),
            )


class CommittedOutputContractTest(unittest.TestCase):
    CSV = ROOT / "data/processed/assignment-08/soil_health_by_field.csv"
    SUMMARY = (
        ROOT / "data/processed/assignment-08/soil_health_summary.json")
    NOTEBOOK = ROOT / "notebooks/08_soil_sustainability.ipynb"
    PNG = ROOT / "docs/assets/soil_health_metrics.png"

    def test_required_artifacts_exist(self):
        for path in (self.CSV, self.SUMMARY, self.NOTEBOOK, self.PNG):
            self.assertTrue(path.is_file(), path)

    def test_csv_has_all_fields_metrics_and_separate_coverage(self):
        rows = pd.read_csv(self.CSV)
        self.assertEqual(rows.columns.tolist(), SOIL_COLUMNS)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows["field_id"].nunique(), 25)
        self.assertEqual(
            rows["field_id"].tolist(), sorted(rows["field_id"]))
        self.assertEqual(
            set(rows["field_id"]),
            {f"STORY-{number:02d}" for number in range(1, 26)},
        )
        for column in (
            "soil_coverage_fraction",
            "om_coverage_fraction",
            "ph_coverage_fraction",
            "cec_coverage_fraction",
            "erosion_coverage_fraction",
            "carbon_coverage_fraction",
        ):
            self.assertTrue(rows[column].between(0, 1).all(), column)
        self.assertTrue(rows["organic_matter_pct"].dropna().gt(0).all())
        self.assertTrue(rows["ph_h2o"].dropna().between(0, 14).all())
        self.assertTrue(rows["cec_cmol_kg"].dropna().ge(0).all())
        self.assertTrue(rows["erosion_k_factor"].dropna().ge(0).all())
        self.assertTrue(
            rows["carbon_storage_mg_c_ha"].dropna().ge(0).all())

    def test_summary_has_five_metrics_units_and_screening_scope(self):
        summary = json.loads(self.SUMMARY.read_text())
        self.assertEqual(summary["field_count"], 25)
        self.assertEqual(summary["depth_limit_cm"], 30)
        self.assertIn("screening", summary["interpretation"].lower())
        self.assertIn("not", summary["interpretation"].lower())
        self.assertEqual(
            set(summary["metrics"]),
            {
                "organic_matter_pct",
                "ph_h2o",
                "cec_cmol_kg",
                "erosion_k_factor",
                "carbon_storage_mg_c_ha",
            },
        )
        self.assertTrue(
            all(metric["unit"] for metric in summary["metrics"].values()))

    def test_notebook_covers_metrics_coverage_and_limitations(self):
        document = json.loads(self.NOTEBOOK.read_text())
        prose = " ".join(
            "".join(cell.get("source", []))
            for cell in document["cells"]
            if cell.get("cell_type") == "markdown"
        ).lower()
        for phrase in (
            "organic matter",
            "ph",
            "cation exchange capacity",
            "erosion",
            "carbon",
            "coverage",
            "missing",
            "limitation",
            "screening",
        ):
            self.assertIn(phrase, prose)
        self.assertRegex(prose, r"not (?:a |an )?(?:farm )?recommendation")

    def test_png_contract(self):
        data = self.PNG.read_bytes()
        self.assertGreater(len(data), 1000)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
