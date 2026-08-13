import csv
import json
import math
import pathlib
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

import scripts.assignment_05 as assignment_05

from scripts.assignment_05 import (
    DATE_RANGE,
    MINIMUM_VALID_FRACTION,
    _reproject_scl,
    calculate_ndvi,
    candidate_sort_key,
    raster_data_mask,
    read_asset_window,
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


class StacCompletenessTest(unittest.TestCase):
    def setUp(self):
        self._original_post = assignment_05.requests.post

    def tearDown(self):
        assignment_05.requests.post = self._original_post

    @staticmethod
    def _fields():
        return gpd.GeoDataFrame(
            geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")

    def _post_returning(self, payload):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        assignment_05.requests.post = (
            lambda url, json=None, timeout=None: FakeResponse())

    @staticmethod
    def _candidate():
        candidate = feature("a", "2023-07-01T00:00:00Z", 1.0)
        candidate["assets"] = {
            name: {"href": f"https://example.invalid/{name}.tif"}
            for name in ("red", "nir", "scl")
        }
        return candidate

    def test_truncated_matched_is_rejected(self):
        self._post_returning({
            "features": [self._candidate()],
            "context": {"matched": 2, "returned": 1},
        })
        with self.assertRaisesRegex(ValueError, "truncated"):
            assignment_05.query_candidates(self._fields())

    def test_rel_next_link_is_rejected(self):
        self._post_returning({
            "features": [self._candidate()],
            "links": [{"rel": "next", "href": "https://example.invalid"}],
        })
        with self.assertRaisesRegex(ValueError, "paginated"):
            assignment_05.query_candidates(self._fields())

    def test_redundant_next_is_allowed_when_context_is_complete(self):
        self._post_returning({
            "features": [self._candidate()],
            "context": {"matched": 1, "returned": 1},
            "links": [{"rel": "next", "href": "https://example.invalid"}],
        })
        self.assertEqual(
            [item["id"] for item in
             assignment_05.query_candidates(self._fields())],
            ["a"],
        )


class ReadAssetWindowTest(unittest.TestCase):
    def test_rejects_raster_not_covering_every_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = pathlib.Path(tmp) / "raw"
            raster_path = raw_dir / "small.tif"
            raster_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                width=10,
                height=10,
                count=1,
                dtype="uint8",
                crs="EPSG:4326",
                transform=from_origin(0, 10, 1, 1),
            ) as target:
                target.write(np.zeros((10, 10), dtype="uint8"), 1)

            fields = gpd.GeoDataFrame(
                geometry=[box(5, 5, 20, 20)], crs="EPSG:4326")
            feature_with_asset = {
                "id": "small",
                "assets": {"red": {"href": raster_path.as_posix()}},
            }

            with self.assertRaisesRegex(ValueError, "does not cover every"):
                read_asset_window(
                    feature_with_asset, "red", fields, raw_dir)


class ReprojectSclTest(unittest.TestCase):
    def test_nearest_neighbor_preserves_categorical_classes(self):
        crs = CRS.from_epsg(3857)
        scl = {
            "array": np.array([[4, 5], [6, 7]], dtype="uint8"),
            "transform": from_origin(0, 40, 20, 20),
            "crs": crs,
            "nodata": 0,
        }
        target = {
            "array": np.zeros((4, 4), dtype="uint8"),
            "transform": from_origin(0, 40, 10, 10),
            "crs": crs,
        }
        result = _reproject_scl(scl, target)
        expected = np.array([
            [4, 4, 5, 5],
            [4, 4, 5, 5],
            [6, 6, 7, 7],
            [6, 6, 7, 7],
        ], dtype="uint8")
        np.testing.assert_array_equal(result, expected)


if __name__ == "__main__":
    unittest.main()
