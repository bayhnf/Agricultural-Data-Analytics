import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import requests
from shapely.geometry import box

from scripts import assignment_02 as assignment_module
from scripts import common as common_module
from scripts.assignment_02 import COUNTY_QUERY, select_grid_fields
from scripts.common import download_atomic


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


if __name__ == "__main__":
    unittest.main()
