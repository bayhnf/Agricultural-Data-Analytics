import hashlib
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box

from scripts import assignment_02 as assignment_module
from scripts import common as common_module
from scripts.assignment_02 import COUNTY_QUERY, select_grid_fields
from scripts.common import download_atomic
from scripts.zonal import categorical_summary, continuous_summary


class FakeResponse:
    def __init__(self, content=b"", headers=None, status_code=200):
        self.content = content
        self.headers = headers or {"content-type": "application/octet-stream"}
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def iter_content(self, chunk_size):
        yield self.content


def make_get(side_effects):
    calls = {"count": 0}

    def fake_get(url, stream=True, timeout=None):
        calls["count"] += 1
        item = side_effects[calls["count"] - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return fake_get, calls


class FieldSelectionTest(unittest.TestCase):
    def test_selects_one_field_per_grid_cell_with_stable_ids(self):
        county = box(0, 0, 50, 50)
        rows = []
        for row in range(5):
            for col in range(5):
                rows.append({
                    "FBndID": f"B-{row}-{col}",
                    "isAG": 1,
                    "geometry": box(col * 10 + 4, row * 10 + 4,
                                    col * 10 + 6, row * 10 + 6),
                })
        fields = gpd.GeoDataFrame(rows, crs=5070)
        selected = select_grid_fields(fields, county)
        self.assertEqual(list(selected["field_id"]),
                         [f"STORY-{number:02d}" for number in range(1, 26)])
        self.assertEqual(len(selected), 25)
        self.assertEqual(selected["source_id"].nunique(), 25)

    def test_rejects_missing_grid_cell(self):
        county = box(0, 0, 50, 50)
        fields = gpd.GeoDataFrame(
            [{"FBndID": "only-one", "isAG": 1, "geometry": box(4, 4, 6, 6)}],
            crs=5070,
        )
        with self.assertRaisesRegex(ValueError, "25 populated grid cells"):
            select_grid_fields(fields, county)

    def test_nearest_centroid_field_wins_within_cell(self):
        county = box(0, 0, 50, 50)
        rows = []
        for row in range(5):
            for col in range(5):
                if (row, col) == (0, 0):
                    rows.append({"FBndID": "far", "isAG": 1,
                                 "geometry": box(6, 4, 8, 6)})
                    rows.append({"FBndID": "near", "isAG": 1,
                                 "geometry": box(4.5, 4, 6.5, 6)})
                    continue
                rows.append({
                    "FBndID": f"cell-{row}-{col}", "isAG": 1,
                    "geometry": box(col * 10 + 4, row * 10 + 4,
                                    col * 10 + 6, row * 10 + 6),
                })
        fields = gpd.GeoDataFrame(rows, crs=5070)
        selected = select_grid_fields(fields, county)
        self.assertIn("near", set(selected["source_id"]))
        self.assertNotIn("far", set(selected["source_id"]))
        self.assertEqual(len(selected), 25)

    def test_fbndid_tie_break_picks_smaller_string_id(self):
        county = box(0, 0, 50, 50)
        rows = []
        for row in range(5):
            for col in range(5):
                if (row, col) == (0, 0):
                    rows.append({"FBndID": "cell-0-0-B", "isAG": 1,
                                 "geometry": box(4, 4, 6, 6)})
                    rows.append({"FBndID": "cell-0-0-A", "isAG": 1,
                                 "geometry": box(4, 4, 6, 6)})
                    continue
                rows.append({
                    "FBndID": f"cell-{row}-{col}", "isAG": 1,
                    "geometry": box(col * 10 + 4, row * 10 + 4,
                                    col * 10 + 6, row * 10 + 6),
                })
        fields = gpd.GeoDataFrame(rows, crs=5070)
        selected = select_grid_fields(fields, county)
        self.assertIn("cell-0-0-A", set(selected["source_id"]))
        self.assertNotIn("cell-0-0-B", set(selected["source_id"]))

    def test_committed_field_contract(self):
        path = "data/processed/assignment-02/fields_EPSG4326.geojson"
        fields = gpd.read_file(path)
        self.assertEqual(len(fields), 25)
        self.assertEqual(fields.crs.to_epsg(), 4326)
        self.assertEqual(fields["field_id"].nunique(), 25)
        self.assertTrue((fields["inside_fraction"] >= 0.95).all())
        self.assertTrue((fields["area_ha"] > 0).all())
        self.assertEqual(set(fields.columns),
                         {"field_id", "source_id", "grid_row", "grid_col",
                          "area_ha", "inside_fraction", "geometry"})
        self.assertTrue(set(fields.geometry.geom_type)
                        <= {"Polygon", "MultiPolygon"})


class CountyQueryTest(unittest.TestCase):
    def test_geoid_is_a_quoted_string_in_tigerweb_query(self):
        self.assertEqual(COUNTY_QUERY["where"], "GEOID='19169'")


class DownloadAtomicTest(unittest.TestCase):
    def test_retries_transient_failures_then_succeeds(self):
        transient_cases = [
            ("http_503", FakeResponse(status_code=503)),
            ("http_429", FakeResponse(status_code=429)),
            ("connection_error", requests.ConnectionError("down")),
        ]
        for label, first in transient_cases:
            with self.subTest(label=label):
                with TemporaryDirectory() as tmp:
                    destination = Path(tmp) / "artifact.bin"
                    get, calls = make_get(
                        [first, FakeResponse(content=b"payload")])
                    sleeps = []
                    with mock.patch.object(common_module.requests, "get", get), \
                            mock.patch.object(common_module.time, "sleep",
                                              sleeps.append):
                        digest = download_atomic("https://example.test/x",
                                                 destination)
                    self.assertEqual(calls["count"], 2, label)
                    self.assertEqual(len(sleeps), 1, label)
                    self.assertEqual(digest,
                                     hashlib.sha256(b"payload").hexdigest())
                    self.assertEqual(destination.read_bytes(), b"payload")

    def test_stops_after_bounded_attempts_and_cleans_tmp(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            get, calls = make_get([requests.ConnectionError("down")] * 3)
            sleeps = []
            with mock.patch.object(common_module.requests, "get", get), \
                    mock.patch.object(common_module.time, "sleep",
                                      sleeps.append):
                with self.assertRaises(requests.ConnectionError):
                    download_atomic("https://example.test/x", destination)
            self.assertEqual(calls["count"], 3)
            self.assertEqual(len(sleeps), 2)
            self.assertFalse(destination.exists())
            self.assertFalse(
                destination.with_suffix(destination.suffix + ".tmp").exists())

    def test_does_not_retry_client_http_errors(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            get, calls = make_get([FakeResponse(status_code=404)])
            sleeps = []
            with mock.patch.object(common_module.requests, "get", get), \
                    mock.patch.object(common_module.time, "sleep",
                                      sleeps.append):
                with self.assertRaises(requests.HTTPError):
                    download_atomic("https://example.test/x", destination)
            self.assertEqual(calls["count"], 1)
            self.assertEqual(sleeps, [])
            self.assertFalse(destination.exists())

    def test_rejects_html_response_without_retry(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            get, calls = make_get([FakeResponse(
                headers={"content-type": "text/html; charset=utf-8"})])
            sleeps = []
            with mock.patch.object(common_module.requests, "get", get), \
                    mock.patch.object(common_module.time, "sleep",
                                      sleeps.append):
                with self.assertRaisesRegex(ValueError,
                                            "refusing HTML response"):
                    download_atomic("https://example.test/x", destination)
            self.assertEqual(calls["count"], 1)
            self.assertEqual(sleeps, [])

    def test_rejects_checksum_mismatch_and_leaves_no_output(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            get, calls = make_get([FakeResponse(content=b"data")])
            with mock.patch.object(common_module.requests, "get", get):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    download_atomic("https://example.test/x", destination,
                                    expected_sha256="0" * 64)
            self.assertEqual(calls["count"], 1)
            self.assertFalse(destination.exists())
            self.assertFalse(
                destination.with_suffix(destination.suffix + ".tmp").exists())


class CachedDownloadTest(unittest.TestCase):
    def test_corrupt_cache_is_replaced_by_redownload(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            destination.write_bytes(b"corrupt")
            correct = b"good-data"
            expected = hashlib.sha256(correct).hexdigest()

            def fake_download(url, target, expected_sha256=None):
                target.write_bytes(correct)
                return expected

            with mock.patch.object(assignment_module, "download_atomic",
                                   fake_download):
                digest, retrieved, cached = assignment_module._cached_download(
                    "https://example.test/x", destination, expected)
            self.assertEqual(digest, expected)
            self.assertEqual(destination.read_bytes(), correct)
            self.assertFalse(cached)
            self.assertIsInstance(retrieved, str)

    def test_valid_cache_is_kept_without_network(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "artifact.bin"
            correct = b"good-data"
            destination.write_bytes(correct)
            expected = hashlib.sha256(correct).hexdigest()

            def unexpected_download(*args, **kwargs):
                raise AssertionError("network must not be used for valid cache")

            with mock.patch.object(assignment_module, "download_atomic",
                                   unexpected_download):
                digest, retrieved, cached = assignment_module._cached_download(
                    "https://example.test/x", destination, expected)
            self.assertEqual(digest, expected)
            self.assertTrue(cached)
            self.assertEqual(destination.read_bytes(), correct)
            self.assertIsInstance(retrieved, str)


class CommittedManifestTest(unittest.TestCase):
    def test_acpf_manifest_marks_cache_use(self):
        manifest = json.loads(
            Path("data/provenance/acpf_fields.json").read_text())
        self.assertIn("retrieved_utc", manifest)
        self.assertIsInstance(manifest["counts"]["cache_used"], bool)


class CategoricalSummaryTest(unittest.TestCase):
    def test_returns_stable_majority_and_coverage(self):
        values = np.array([[1, 1], [5, 0]], dtype="uint8")
        result = categorical_summary(values, values != 0,
                                     minimum_coverage=0.70)
        self.assertEqual(result["value"], 1)
        self.assertEqual(result["valid_pixels"], 3)
        self.assertEqual(result["total_pixels"], 4)
        self.assertAlmostEqual(result["coverage_fraction"], 0.75)
        self.assertAlmostEqual(result["majority_fraction"], 2 / 3)

    def test_nulls_class_when_coverage_is_too_low(self):
        values = np.array([[1, 0], [0, 0]], dtype="uint8")
        result = categorical_summary(values, values != 0,
                                     minimum_coverage=0.70)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["majority_fraction"])

    def test_count_tie_chooses_lowest_numeric_code(self):
        values = np.array([[2, 2], [1, 1]], dtype="uint8")
        result = categorical_summary(values, values != 0,
                                     minimum_coverage=0.0)
        self.assertEqual(result["value"], 1)
        self.assertAlmostEqual(result["majority_fraction"], 0.5)

    def test_exactly_at_coverage_threshold_keeps_class(self):
        values = np.array([1] * 7 + [0] * 3, dtype="uint8")
        result = categorical_summary(values, values != 0,
                                     minimum_coverage=0.70)
        self.assertEqual(result["value"], 1)
        self.assertAlmostEqual(result["coverage_fraction"], 0.7)


class ContinuousSummaryTest(unittest.TestCase):
    def test_ignores_non_finite_pixels(self):
        values = np.array([1.0, 2.0, np.nan, np.inf, -np.inf, 3.0])
        result = continuous_summary(values,
                                    np.ones(values.shape, dtype=bool))
        self.assertEqual(result["valid_pixels"], 3)
        self.assertEqual(result["total_pixels"], 6)
        self.assertAlmostEqual(result["coverage_fraction"], 0.5)
        self.assertAlmostEqual(result["mean"], 2.0)
        self.assertAlmostEqual(result["median"], 2.0)

    def test_nulls_when_no_finite_pixels(self):
        values = np.array([np.nan, np.inf, -np.inf])
        result = continuous_summary(values,
                                    np.ones(values.shape, dtype=bool))
        self.assertIsNone(result["mean"])
        self.assertIsNone(result["median"])
        self.assertEqual(result["valid_pixels"], 0)
        self.assertEqual(result["total_pixels"], 3)
        self.assertEqual(result["coverage_fraction"], 0.0)


class CdlServiceXmlTest(unittest.TestCase):
    def test_parses_return_url_from_namespaced_response(self):
        xml_text = (
            '<ns1:GetCDLFileResponse '
            'xmlns:ns1="http://cropscape.csiss.gmu.edu/CDLService/">'
            '<returnURL>https://nassgeodata.gmu.edu/webservice/'
            'nass_data_cache/byfips/CDL_2023_19169.tif</returnURL>'
            '</ns1:GetCDLFileResponse>'
        )
        self.assertEqual(
            assignment_module.parse_return_url(xml_text),
            "https://nassgeodata.gmu.edu/webservice/"
            "nass_data_cache/byfips/CDL_2023_19169.tif",
        )

    def test_rejects_response_without_return_url(self):
        with self.assertRaisesRegex(ValueError, "returnURL"):
            assignment_module.parse_return_url(
                "<ns1:GetCDLFileResponse xmlns:ns1=\"http://cropscape.csiss.gmu.edu/CDLService/\">"
                "<other/></ns1:GetCDLFileResponse>"
            )

    def test_service_url_encodes_year_and_fips(self):
        self.assertEqual(assignment_module.cdl_service_url(2023),
                         assignment_module.CDL_SERVICE_URL
                         + "?fips=19169&year=2023")
        self.assertEqual(assignment_module.CDL_YEARS,
                         (2020, 2021, 2022, 2023))


class CdlMetadataTest(unittest.TestCase):
    def test_parses_official_code_domain_across_pre_blocks(self):
        html_text = (
            "<pre>accuracy table\nCorn 1 340,138\n</pre>\n"
            "<pre>\n"
            " Categorization Code   Land Cover\n"
            '         &quot;0&quot;       Background\n'
            '           &quot;1&quot;       Corn\n'
            '           &quot;5&quot;       Soybeans\n'
            '          &quot;26&quot;       Dbl Crop WinWht/Soybeans\n'
            '          &quot;47&quot;       Misc Vegs &amp; Fruits\n'
            "</pre>\n"
        )
        self.assertEqual(
            assignment_module.parse_cdl_labels(html_text),
            {0: "Background", 1: "Corn", 5: "Soybeans",
             26: "Dbl Crop WinWht/Soybeans",
             47: "Misc Vegs & Fruits"},
        )

    def test_rejects_missing_dictionary(self):
        with self.assertRaisesRegex(ValueError, "code/name"):
            assignment_module.parse_cdl_labels("<html>no dictionary</html>")


class RasterMaskingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.raster_path = Path(self.tmp.name) / "crops.tif"
        cell = 30.0
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070",
                                           always_xy=True)
        x0, y0 = transformer.transform(-93.6, 42.0)
        transform = from_origin(x0, y0 + cell * 4, cell, cell)
        data = np.array([
            [1, 1, 0, 0],
            [1, 0, 0, 0],
            [5, 5, 5, 0],
            [5, 5, 5, 0],
        ], dtype="uint8")
        with rasterio.open(self.raster_path, "w", driver="GTiff",
                           width=4, height=4, count=1, dtype="uint8",
                           crs="EPSG:5070", transform=transform) as dst:
            dst.write(data, 1)
        left = box(x0 + 10, y0 + 50, x0 + 60, y0 + 130)
        right = box(x0 + 60, y0 + 50, x0 + 140, y0 + 130)
        self.fields = gpd.GeoDataFrame(
            {"field_id": ["left", "right"], "geometry": [left, right]},
            crs="EPSG:5070",
        ).to_crs(4326)

    def tearDown(self):
        self.tmp.cleanup()

    def test_masks_in_raster_crs_with_one_row_per_field(self):
        rows = assignment_module.summarize_field_year(self.raster_path,
                                                      self.fields)
        self.assertEqual(len(rows), 2)
        by_id = {row["field_id"]: row for row in rows}
        left = by_id["left"]
        self.assertEqual(left["value"], 1)
        self.assertEqual(left["valid_pixels"], 3)
        self.assertEqual(left["total_pixels"], 4)
        self.assertAlmostEqual(left["coverage_fraction"], 0.75)
        self.assertAlmostEqual(left["majority_fraction"], 1.0)
        right = by_id["right"]
        self.assertIsNone(right["value"])
        self.assertEqual(right["valid_pixels"], 0)
        self.assertEqual(right["total_pixels"], 4)
        self.assertEqual(right["coverage_fraction"], 0.0)


class CdlAcquisitionPathTest(unittest.TestCase):
    def test_every_year_uses_the_official_service_download_path(self):
        self.assertFalse(hasattr(assignment_module, "VERIFIED_2023_CACHE"))
        self.assertNotIn("shutil", assignment_module.__dict__)
        for year in assignment_module.CDL_YEARS:
            with self.subTest(year=year):
                with TemporaryDirectory() as tmp:
                    raw_dir = Path(tmp)
                    return_url = (f"https://example.test/"
                                  f"CDL_{year}_19169.tif")
                    with mock.patch.object(
                            assignment_module, "_cached_download",
                            return_value=("digest", "retrieved", True)
                    ) as cached:
                        result = assignment_module._acquire_cdl_raster(
                            year, return_url, raw_dir)
                    cached.assert_called_once_with(
                        return_url, raw_dir / f"CDL_{year}_19169.tif")
                    self.assertEqual(result, (
                        raw_dir / f"CDL_{year}_19169.tif",
                        "digest", "retrieved", True))


class Assignment02ProductContractTest(unittest.TestCase):
    CROPS_PATH = Path("data/processed/assignment-02/cdl_EPSG4326.csv")
    JOINED_PATH = Path("data/processed/assignment-02/fields_with_crops.geojson")
    SUMMARY_PATH = Path("data/processed/assignment-02/field_summary.csv")
    MAP_PATH = Path("data/processed/assignment-02/my_fields_map.html")

    def test_assignment_02_products(self):
        crops = pd.read_csv(self.CROPS_PATH)
        self.assertEqual(list(crops.columns), [
            "field_id", "year", "cdl_code", "cdl_name",
            "majority_fraction", "coverage_fraction",
            "valid_pixels", "total_pixels",
        ])
        self.assertEqual(len(crops), 100)
        self.assertEqual(set(crops["year"]), {2020, 2021, 2022, 2023})
        self.assertFalse(crops.duplicated(["field_id", "year"]).any())

        joined = gpd.read_file(self.JOINED_PATH)
        self.assertEqual(len(joined), 25)
        self.assertEqual(joined["field_id"].nunique(), 25)

    def test_crops_are_stably_sorted_by_field_and_year(self):
        crops = pd.read_csv(self.CROPS_PATH)
        keys = crops[["field_id", "year"]].values.tolist()
        self.assertEqual(keys, sorted(keys))

    def test_joined_geometry_contract(self):
        joined = gpd.read_file(self.JOINED_PATH)
        self.assertEqual(joined.crs.to_epsg(), 4326)
        base = {"field_id", "source_id", "grid_row", "grid_col",
                "area_ha", "inside_fraction", "geometry"}
        self.assertTrue(base <= set(joined.columns))
        for year in (2020, 2021, 2022, 2023):
            for suffix in ("code", "name", "fraction", "coverage"):
                self.assertIn(f"crop_{year}_{suffix}", joined.columns)
            self.assertTrue(joined[f"crop_{year}_fraction"]
                            .between(0.0, 1.0).all())
            self.assertTrue(joined[f"crop_{year}_coverage"]
                            .between(0.0, 1.0).all())

    def test_summary_contract(self):
        summary = pd.read_csv(self.SUMMARY_PATH)
        self.assertEqual(list(summary.columns), [
            "field_count", "total_area_ha", "mean_area_ha",
            "median_area_ha", "crop_record_count",
            "missing_crop_record_count", "duplicate_field_id_count",
        ])
        self.assertEqual(len(summary), 1)
        self.assertEqual(int(summary.loc[0, "field_count"]), 25)
        self.assertEqual(int(summary.loc[0, "crop_record_count"]), 100)
        self.assertEqual(int(summary.loc[0, "missing_crop_record_count"]), 0)
        self.assertEqual(int(summary.loc[0, "duplicate_field_id_count"]), 0)
        self.assertGreater(float(summary.loc[0, "total_area_ha"]), 0.0)

    def test_crop_names_come_from_the_official_domain(self):
        metadata = Path("data/raw/cdl_metadata_ia23.htm")
        if not metadata.is_file():
            self.skipTest("CDL metadata cache not present")
        official = assignment_module.parse_cdl_labels(
            metadata.read_text(errors="replace"))
        crops = pd.read_csv(self.CROPS_PATH)
        for _, row in crops.dropna(subset=["cdl_name"]).iterrows():
            self.assertEqual(official[int(row["cdl_code"])],
                             row["cdl_name"])

    def test_map_embeds_only_the_25_field_geojson(self):
        text = self.MAP_PATH.read_text()
        self.assertIn(
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", text)
        self.assertIn(
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", text)
        self.assertIn("L.map", text)
        self.assertNotIn("data/raw", text)
        match = re.search(r"^var fields = (\{.*\});$", text, re.M)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(len(payload["features"]), 25)
        ids = {feature["properties"]["field_id"]
               for feature in payload["features"]}
        self.assertEqual(ids, {f"STORY-{number:02d}"
                               for number in range(1, 26)})


if __name__ == "__main__":
    unittest.main()
