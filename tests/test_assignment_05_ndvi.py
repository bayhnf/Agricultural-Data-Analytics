import csv
import json
import math
import pathlib
import unittest

import numpy as np

from scripts.assignment_05 import (
    DATE_RANGE,
    MINIMUM_VALID_FRACTION,
    calculate_ndvi,
    candidate_sort_key,
    raster_data_mask,
    select_scene_candidate,
    sort_candidates,
    stac_search_payload,
    valid_scl_fraction,
    valid_scl_mask,
)


ROOT = pathlib.Path(__file__).parents[1]


def feature(scene_id, datetime, cloud_cover):
    return {
        "id": scene_id,
        "properties": {
            "datetime": datetime,
            "eo:cloud_cover": cloud_cover,
        },
    }


class CloudMaskTest(unittest.TestCase):
    def test_scl_excludes_invalid_classes(self):
        scl = np.arange(12, dtype="uint8")
        self.assertEqual(
            valid_scl_mask(scl).tolist(),
            [False, False, False, False, True, True,
             True, True, False, False, False, False],
        )

    def test_valid_scl_fraction_ignores_outside_field_pixels(self):
        scl = np.array([4, 8, 0], dtype="uint8")
        field_mask = np.array([True, False, True])
        self.assertEqual(valid_scl_fraction(scl, field_mask), 0.5)

    def test_valid_scl_fraction_returns_zero_without_field_pixels(self):
        scl = np.array([4, 8], dtype="uint8")
        field_mask = np.array([False, False])
        self.assertEqual(valid_scl_fraction(scl, field_mask), 0.0)


class NdviCalculationTest(unittest.TestCase):
    def test_applies_stac_scale_and_offset_before_ndvi(self):
        red = np.array([[2000]], dtype="uint16")
        nir = np.array([[5000]], dtype="uint16")
        result = calculate_ndvi(
            red, nir, scale=0.0001, offset=-0.1,
            valid_mask=np.array([[True]]),
        )
        self.assertAlmostEqual(float(result[0, 0]), 0.6)

    def test_masks_invalid_and_zero_denominator_pixels(self):
        red = np.array([[0, 0, 1000]], dtype="uint16")
        nir = np.array([[0, 1000, 1000]], dtype="uint16")
        valid = np.array([[False, True, True]])
        result = calculate_ndvi(red, nir, 0.0001, -0.1, valid)
        self.assertTrue(math.isnan(float(result[0, 0])))
        self.assertAlmostEqual(float(result[0, 1]), -1.0)
        self.assertTrue(math.isnan(float(result[0, 2])))

    def test_clips_finite_ndvi_to_unit_interval(self):
        red = np.array([[0]], dtype="uint16")
        nir = np.array([[5000]], dtype="uint16")
        result = calculate_ndvi(red, nir, 0.0001, -0.1,
                                np.array([[True]]))
        self.assertEqual(float(result[0, 0]), 1.0)

    def test_applies_each_assets_scale_and_offset(self):
        result = calculate_ndvi(
            np.array([[2000]], dtype="uint16"),
            np.array([[5000]], dtype="uint16"),
            scale=0.0001,
            offset=-0.1,
            valid_mask=np.array([[True]]),
            nir_scale=0.0002,
            nir_offset=-0.2,
        )
        self.assertAlmostEqual(float(result[0, 0]), 7 / 9)

    def test_raw_data_mask_rejects_nodata_and_non_finite_values(self):
        values = np.array([0.0, 1.0, np.nan])
        self.assertEqual(
            raster_data_mask(values, nodata=0).tolist(),
            [False, True, False],
        )


class SceneSelectionTest(unittest.TestCase):
    def test_stac_query_uses_exact_collection_and_window(self):
        payload = stac_search_payload((-94.0, 41.0, -93.0, 42.0))
        self.assertEqual(payload["collections"], ["sentinel-2-l2a"])
        self.assertEqual(
            payload["datetime"],
            "2023-06-01T00:00:00Z/2023-08-31T23:59:59Z",
        )
        self.assertEqual(DATE_RANGE, payload["datetime"])

    def test_deterministic_sort_uses_cloud_datetime_and_id(self):
        features = [
            feature("c", "2023-07-01T00:00:00Z", 20.0),
            feature("a", "2023-07-01T00:00:00Z", 5.0),
            feature("b", "2023-07-01T00:00:00Z", 5.0),
            feature("d", "2023-06-01T00:00:00Z", 5.0),
        ]
        ordered = sort_candidates(features)
        self.assertEqual([f["id"] for f in ordered], ["d", "a", "b", "c"])

    def test_missing_cloud_cover_sorts_last(self):
        features = [
            feature("cloudy", "2023-07-01T00:00:00Z", 10.0),
            feature("unknown", "2023-07-01T00:00:00Z", None),
        ]
        self.assertEqual(
            candidate_sort_key(features[0]),
            (10.0, "2023-07-01T00:00:00Z", "cloudy"),
        )
        self.assertGreater(
            candidate_sort_key(features[1]),
            candidate_sort_key(features[0]),
        )

    def test_selects_first_scene_above_threshold_and_logs_rejections(self):
        windows = {
            "low": (np.array([4, 8], dtype="uint8"),
                    np.array([True, True])),
            "ok": (np.array([4, 7], dtype="uint8"),
                   np.array([True, True])),
        }

        def reader(item):
            return windows[item["id"]]

        features = [
            feature("low", "2023-07-01T00:00:00Z", 1.0),
            feature("ok", "2023-07-02T00:00:00Z", 1.0),
        ]
        selected, fraction, rejected = select_scene_candidate(features, reader)
        self.assertEqual(selected["id"], "ok")
        self.assertAlmostEqual(fraction, 1.0)
        self.assertEqual(rejected, [
            {"scene_id": "low", "valid_scl_fraction": 0.5},
        ])

    def test_raises_when_no_scene_meets_threshold(self):
        def reader(item):
            return (np.array([8], dtype="uint8"), np.array([True]))

        with self.assertRaisesRegex(ValueError, "no scene"):
            select_scene_candidate(
                [feature("bad", "2023-07-01T00:00:00Z", 1.0)], reader)


class CommittedOutputContractTest(unittest.TestCase):
    def test_required_task_7_artifacts_exist(self):
        for relative in (
            "data/provenance/sentinel_2023.json",
            "data/processed/assignment-05/scene.json",
            "data/processed/assignment-05/field_ndvi.csv",
            "notebooks/05_satellite_ndvi.ipynb",
            "docs/assets/sentinel_red_band.png",
            "docs/assets/ndvi_map.png",
            "docs/reports/assignment-05-walkthrough.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_scene_csv_provenance_and_figure_contracts(self):
        scene = json.loads(
            (ROOT / "data/processed/assignment-05/scene.json").read_text())
        self.assertEqual(scene["collection"], "sentinel-2-l2a")
        self.assertEqual(scene["search_datetime"], DATE_RANGE)
        self.assertGreaterEqual(
            scene["study_area_valid_scl_fraction"],
            MINIMUM_VALID_FRACTION,
        )
        self.assertTrue(scene["selected_scene_id"].startswith("S2"))
        self.assertTrue(scene["selected_scene_datetime"].startswith("2023-"))
        self.assertEqual(scene["valid_scl_classes"], [4, 5, 6, 7])
        for rejected in scene["rejected_candidates"]:
            self.assertLess(
                rejected["valid_scl_fraction"], MINIMUM_VALID_FRACTION)

        csv_path = ROOT / "data/processed/assignment-05/field_ndvi.csv"
        with csv_path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        self.assertEqual(
            reader.fieldnames,
            ["field_id", "mean_ndvi", "median_ndvi",
             "valid_pixel_count", "total_pixel_count",
             "coverage_fraction"],
        )
        self.assertEqual(len(rows), 25)
        self.assertEqual(
            [row["field_id"] for row in rows],
            sorted(row["field_id"] for row in rows),
        )
        self.assertEqual(len({row["field_id"] for row in rows}), 25)
        for row in rows:
            valid = int(row["valid_pixel_count"])
            total = int(row["total_pixel_count"])
            coverage = float(row["coverage_fraction"])
            self.assertLessEqual(valid, total)
            self.assertGreater(total, 0)
            self.assertAlmostEqual(coverage, valid / total)
            self.assertLessEqual(-1.0, float(row["mean_ndvi"]))
            self.assertLessEqual(float(row["mean_ndvi"]), 1.0)
            self.assertLessEqual(-1.0, float(row["median_ndvi"]))
            self.assertLessEqual(float(row["median_ndvi"]), 1.0)

        provenance = json.loads(
            (ROOT / "data/provenance/sentinel_2023.json").read_text())
        for key in (
            "dataset", "source_organization", "source_name", "source_urls",
            "retrieved_utc", "source_version", "sha256", "source_crs",
            "output_crs", "producer", "counts", "license_note",
        ):
            self.assertIn(key, provenance)
        self.assertEqual(provenance["counts"]["fields"], 25)
        self.assertEqual(provenance["counts"]["csv_rows"], 25)
        self.assertEqual(len(provenance["sha256"]), 3)

        for relative in (
            "docs/assets/sentinel_red_band.png",
            "docs/assets/ndvi_map.png",
        ):
            self.assertGreater((ROOT / relative).stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
