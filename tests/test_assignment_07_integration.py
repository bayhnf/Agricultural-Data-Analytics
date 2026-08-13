import json
import pathlib
import unittest

import geopandas as gpd
import pandas as pd

from scripts.assignment_07 import (
    build_integrated_dataset,
    derive_dominant_soils,
    integrate_fields,
)


ROOT = pathlib.Path(__file__).parents[1]
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


def fields_frame(*field_ids):
    return pd.DataFrame({"field_id": list(field_ids)})


def crops_frame(*rows):
    return pd.DataFrame(
        rows, columns=["field_id", "crop_2023_name"])


def soils_frame(*rows):
    return pd.DataFrame(
        rows,
        columns=[
            "field_id",
            "dominant_soil",
            "dominant_soil_name",
            "dominant_soil_mukey",
            "dominant_soil_overlap_area_ha",
        ],
    )


def ndvi_frame(*rows):
    return pd.DataFrame(
        rows,
        columns=[
            "field_id",
            "mean_ndvi",
            "valid_pixel_count",
            "total_pixel_count",
            "coverage_fraction",
        ],
    )


class DominantSoilTest(unittest.TestCase):
    def test_selects_largest_overlap_then_lexical_mukey(self):
        overlaps = pd.DataFrame({
            "field_id": ["A", "A", "B", "B"],
            "mukey": ["9", "10", "2", "3"],
            "musym": ["s9", "s10", "s2", "s3"],
            "muname": ["nine", "ten", "two", "three"],
            "overlap_area_ha": [5.0, 5.0, 2.0, 7.0],
        })
        result = derive_dominant_soils(overlaps)
        by_field = result.set_index("field_id")
        self.assertEqual(by_field.loc["A", "dominant_soil_mukey"], "10")
        self.assertEqual(by_field.loc["A", "dominant_soil"], "s10")
        self.assertEqual(by_field.loc["B", "dominant_soil_mukey"], "3")
        self.assertEqual(
            by_field.loc["B", "dominant_soil_overlap_area_ha"], 7.0)

    def test_real_input_boundary_converts_square_metres_to_hectares(self):
        fields = fields_frame("A")
        crops = pd.DataFrame({
            "field_id": ["A", "A"],
            "year": [2022, 2023],
            "cdl_name": ["Soybeans", "Corn"],
        })
        overlaps = pd.DataFrame({
            "field_id": ["A", "A"],
            "mukey": ["1", "2"],
            "musym": ["one", "two"],
            "muname": ["first", "second"],
            "overlap_area_m2": [40000.0, 10000.0],
        })
        ndvi = ndvi_frame(("A", 0.7, 10, 10, 1.0))
        result = build_integrated_dataset(fields, crops, overlaps, ndvi)
        self.assertEqual(result.loc[0, "crop_2023_name"], "Corn")
        self.assertEqual(result.loc[0, "dominant_soil_mukey"], "1")
        self.assertEqual(
            result.loc[0, "dominant_soil_overlap_area_ha"], 4.0)


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.fields = fields_frame("B", "A")
        self.crops = crops_frame(("A", "Corn"), ("B", "Soybeans"))
        self.soils = soils_frame(
            ("A", "108", "Clarion loam", "1", 2.0),
            ("B", "108B", "Clarion loam", "2", 3.0),
        )
        self.ndvi = ndvi_frame(
            ("A", 0.7, 9, 10, 0.9),
            ("B", None, 2, 10, 0.2),
        )

    def _integrate(self, fields=None, crops=None, soils=None, ndvi=None):
        return integrate_fields(
            self.fields if fields is None else fields,
            self.crops if crops is None else crops,
            self.soils if soils is None else soils,
            self.ndvi if ndvi is None else ndvi,
        )

    def test_preserves_all_fields_sorted_and_keeps_null_ndvi(self):
        result = self._integrate()
        self.assertEqual(result["field_id"].tolist(), ["A", "B"])
        self.assertTrue(pd.isna(result.loc[1, "mean_ndvi"]))
        self.assertEqual(result.loc[1, "ndvi_coverage_fraction"], 0.2)

    def test_accepts_brief_minimum_soil_and_ndvi_columns(self):
        result = integrate_fields(
            fields_frame("A", "B"),
            crops_frame(("A", "Corn"), ("B", "Soybeans")),
            pd.DataFrame({
                "field_id": ["A", "B"],
                "dominant_soil": ["108", "108B"],
            }),
            pd.DataFrame({
                "field_id": ["A", "B"],
                "mean_ndvi": [0.7, None],
                "coverage_fraction": [0.9, 0.2],
            }),
        )
        self.assertEqual(result["field_id"].tolist(), ["A", "B"])
        self.assertTrue(pd.isna(result.loc[1, "mean_ndvi"]))

    def test_rejects_duplicate_one_to_one_inputs(self):
        cases = {
            "fields": (
                pd.concat([self.fields, fields_frame("A")]),
                None, None, None,
            ),
            "crops": (
                None,
                pd.concat([self.crops, crops_frame(("A", "Oats"))]),
                None, None,
            ),
            "soils": (
                None, None,
                pd.concat([
                    self.soils,
                    soils_frame(("A", "W", "Water", "3", 1.0)),
                ]),
                None,
            ),
            "ndvi": (
                None, None, None,
                pd.concat([
                    self.ndvi,
                    ndvi_frame(("A", 0.6, 8, 10, 0.8)),
                ]),
            ),
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "unique field_id"):
                    self._integrate(*values)

    def test_rejects_missing_or_extra_keys_in_every_join(self):
        cases = {
            "missing crop": (
                None, crops_frame(("A", "Corn")), None, None),
            "missing soil": (
                None, None,
                soils_frame(("A", "108", "Clarion", "1", 2.0)), None),
            "missing ndvi": (
                None, None, None,
                ndvi_frame(("A", 0.7, 9, 10, 0.9))),
            "extra crop": (
                None,
                pd.concat([self.crops, crops_frame(("C", "Oats"))]),
                None, None,
            ),
            "extra soil": (
                None, None,
                pd.concat([
                    self.soils,
                    soils_frame(("C", "W", "Water", "3", 1.0)),
                ]),
                None,
            ),
            "extra ndvi": (
                None, None, None,
                pd.concat([
                    self.ndvi,
                    ndvi_frame(("C", 0.5, 5, 10, 0.5)),
                ]),
            ),
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "field_id keys"):
                    self._integrate(*values)

    def test_emits_canonical_columns_and_renames_ndvi_coverage(self):
        result = self._integrate()
        self.assertEqual(result.columns.tolist(), INTEGRATED_COLUMNS)
        self.assertNotIn("coverage_fraction", result.columns)
        self.assertEqual(result.loc[0, "valid_pixel_count"], 9)
        self.assertEqual(result.loc[0, "total_pixel_count"], 10)


class CommittedOutputContractTest(unittest.TestCase):
    SUMMARY = (
        ROOT / "data/processed/assignment-07/integrated_field_summary.csv")
    GEOJSON = (
        ROOT / "data/processed/assignment-07/integrated_fields.geojson")
    NOTEBOOK = ROOT / "notebooks/07_spatial_integration.ipynb"
    PNG = ROOT / "docs/assets/integrated_spatial_analysis.png"

    def test_required_artifacts_exist(self):
        for path in (self.SUMMARY, self.GEOJSON, self.NOTEBOOK, self.PNG):
            self.assertTrue(path.is_file(), path)

    def test_csv_has_25_sorted_fields_and_ndvi_evidence(self):
        rows = pd.read_csv(
            self.SUMMARY, dtype={"dominant_soil_mukey": str})
        self.assertEqual(rows.columns.tolist(), INTEGRATED_COLUMNS)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows["field_id"].nunique(), 25)
        self.assertEqual(
            rows["field_id"].tolist(), sorted(rows["field_id"]))
        self.assertEqual(
            set(rows["field_id"]),
            {f"STORY-{number:02d}" for number in range(1, 26)},
        )
        self.assertTrue(rows["crop_2023_name"].str.len().gt(0).all())
        self.assertTrue(rows["dominant_soil"].str.len().gt(0).all())
        self.assertTrue(
            rows["dominant_soil_overlap_area_ha"].gt(0).all())
        self.assertTrue(
            rows["valid_pixel_count"].le(rows["total_pixel_count"]).all())
        self.assertTrue(rows["total_pixel_count"].gt(0).all())
        self.assertTrue(
            rows["ndvi_coverage_fraction"].between(0, 1).all())
        self.assertTrue(
            rows["mean_ndvi"].dropna().between(-1, 1).all())

    def test_geojson_is_epsg4326_and_matches_csv(self):
        fields = gpd.read_file(self.GEOJSON)
        summary = pd.read_csv(
            self.SUMMARY, dtype={"dominant_soil_mukey": str})
        self.assertEqual(fields.crs.to_epsg(), 4326)
        self.assertEqual(len(fields), 25)
        self.assertEqual(
            fields.columns.tolist(), INTEGRATED_COLUMNS + ["geometry"])
        self.assertEqual(
            fields["field_id"].tolist(), summary["field_id"].tolist())
        self.assertFalse(fields.geometry.isna().any())
        self.assertFalse(fields.geometry.is_empty.any())

    def test_dominant_soil_matches_assignment_04_source(self):
        overlaps = pd.read_csv(
            ROOT / "data/processed/assignment-04/field_soil_overlap.csv",
            dtype={"mukey": str, "musym": str},
        )
        expected = (
            overlaps
            .sort_values(
                ["field_id", "overlap_area_m2", "mukey"],
                ascending=[True, False, True],
                kind="stable",
            )
            .drop_duplicates("field_id")
            .set_index("field_id")["musym"]
        )
        actual = (
            pd.read_csv(self.SUMMARY)
            .set_index("field_id")["dominant_soil"]
        )
        self.assertEqual(actual.to_dict(), expected.to_dict())

    def test_notebook_explains_method_coverage_and_noncausal_comparison(self):
        document = json.loads(self.NOTEBOOK.read_text())
        prose = " ".join(
            "".join(cell.get("source", []))
            for cell in document["cells"]
            if cell.get("cell_type") == "markdown"
        ).lower()
        self.assertIn("zonal statistics", prose)
        self.assertRegex(prose, r"valid[- ]pixel")
        self.assertIn("coverage", prose)
        self.assertRegex(
            prose, r"not imply causation|not evidence of causation")

    def test_png_contract(self):
        data = self.PNG.read_bytes()
        self.assertGreater(len(data), 1000)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
