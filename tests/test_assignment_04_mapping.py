import json
import re
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from scripts import assignment_04 as assignment_module
from scripts.assignment_04 import (
    ARCHIVE_NAME,
    REQUIRED_MEMBERS,
    calculate_field_soil_overlap,
    normalize_mukey,
    parse_mapunit_column_order,
    read_mapunit_table,
)
from scripts.common import sha256_file


def make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def valid_members() -> dict[str, bytes]:
    return {name: b"payload" for name in REQUIRED_MEMBERS}


class SoilOverlapTest(unittest.TestCase):
    def test_reports_area_fraction_per_field(self):
        fields = gpd.GeoDataFrame(
            [{"field_id": "STORY-01", "geometry": box(0, 0, 10, 10)}],
            crs=5070,
        )
        soils = gpd.GeoDataFrame([
            {"mukey": "A", "geometry": box(0, 0, 5, 10)},
            {"mukey": "B", "geometry": box(5, 0, 10, 10)},
        ], crs=5070)
        result = calculate_field_soil_overlap(fields, soils)
        self.assertEqual(list(result["mukey"]), ["A", "B"])
        self.assertAlmostEqual(result["field_fraction"].sum(), 1.0)

    def test_partial_coverage_fraction_is_not_normalized(self):
        fields = gpd.GeoDataFrame(
            [{"field_id": "STORY-01", "geometry": box(0, 0, 10, 10)}],
            crs=5070,
        )
        soils = gpd.GeoDataFrame(
            [{"mukey": "A", "geometry": box(0, 0, 5, 10)}], crs=5070)
        result = calculate_field_soil_overlap(fields, soils)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.loc[0, "field_fraction"], 0.5)

    def test_merges_same_mukey_without_double_counting(self):
        fields = gpd.GeoDataFrame(
            [{"field_id": "STORY-01", "geometry": box(0, 0, 10, 10)}],
            crs=5070,
        )
        soils = gpd.GeoDataFrame([
            {"mukey": "A", "geometry": box(0, 0, 5, 10)},
            {"mukey": "A", "geometry": box(5, 0, 10, 10)},
        ], crs=5070)
        result = calculate_field_soil_overlap(fields, soils)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.loc[0, "field_fraction"], 1.0)

    def test_stable_sorts_by_field_then_mukey(self):
        fields = gpd.GeoDataFrame([
            {"field_id": "STORY-02", "geometry": box(0, 0, 10, 10)},
            {"field_id": "STORY-01", "geometry": box(20, 0, 30, 10)},
        ], crs=5070)
        soils = gpd.GeoDataFrame([
            {"mukey": "B", "geometry": box(0, 0, 10, 10)},
            {"mukey": "A", "geometry": box(20, 0, 30, 10)},
        ], crs=5070)
        result = calculate_field_soil_overlap(fields, soils)
        keys = result[["field_id", "mukey"]].values.tolist()
        self.assertEqual(keys, [["STORY-01", "A"], ["STORY-02", "B"]])

    def test_requires_crs_and_required_columns(self):
        fields = gpd.GeoDataFrame(
            [{"field_id": "STORY-01", "geometry": box(0, 0, 1, 1)}])
        soils = gpd.GeoDataFrame(
            [{"mukey": "A", "geometry": box(0, 0, 1, 1)}])
        with self.assertRaisesRegex(ValueError, "CRS"):
            calculate_field_soil_overlap(fields, soils)
        with self.assertRaisesRegex(ValueError, "field_id"):
            calculate_field_soil_overlap(
                gpd.GeoDataFrame([{"geometry": box(0, 0, 1, 1)}], crs=5070),
                gpd.GeoDataFrame([{"mukey": "A", "geometry": box(0, 0, 1, 1)}],
                                 crs=5070))
        with self.assertRaisesRegex(ValueError, "mukey"):
            calculate_field_soil_overlap(
                gpd.GeoDataFrame(
                    [{"field_id": "STORY-01", "geometry": box(0, 0, 1, 1)}],
                    crs=5070),
                gpd.GeoDataFrame([{"geometry": box(0, 0, 1, 1)}], crs=5070))


class NormalizeMukeyTest(unittest.TestCase):
    def test_strips_and_stringifies(self):
        self.assertEqual(normalize_mukey(" 2765537 "), "2765537")
        self.assertEqual(normalize_mukey(2765537), "2765537")

    def test_rejects_empty(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            normalize_mukey("   ")


MAPUNIT_METADATA = (
    '"mapunit"|1|"musym"|"mapunit_symbol"|"Mapunit Symbol"|"String"|"Yes"|6'
    '||||||"The symbol used to uniquely identify the soil mapunit."\n'
    '"mapunit"|2|"muname"|"mapunit_name"|"Mapunit Name"|"String"|"No"|175'
    '||||||"Correlated name of the mapunit."\n'
    '"mapunit"|3|"mukey"|"mapunit_key"|"Mapunit Key"|"String"|"Yes"|30'
    '||||||"A non-connotative string of characters."\n'
)


class MapunitColumnTest(unittest.TestCase):
    def test_resolves_order_from_metadata_not_position_constants(self):
        self.assertEqual(parse_mapunit_column_order(MAPUNIT_METADATA),
                         ["musym", "muname", "mukey"])

    def test_rejects_missing_table_metadata(self):
        with self.assertRaisesRegex(ValueError, "no mapunit"):
            parse_mapunit_column_order('"chorizon"|1|"hzname"|"x"|"y"\n')

    def test_rejects_non_contiguous_ordinals(self):
        with self.assertRaisesRegex(ValueError, "contiguous"):
            parse_mapunit_column_order(
                '"mapunit"|1|"musym"|"a"|"b"|"c"\n'
                '"mapunit"|4|"mukey"|"a"|"b"|"c"\n'
                '"mapunit"|2|"muname"|"a"|"b"|"c"\n')

    def test_rejects_missing_required_columns(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            parse_mapunit_column_order(
                '"mapunit"|1|"musym"|"a"|"b"|"c"\n'
                '"mapunit"|2|"muname"|"a"|"b"|"c"\n')


class MapunitTableTest(unittest.TestCase):
    def test_reads_rows_by_metadata_derived_positions(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapunit.txt"
            path.write_text(
                '"108"|"Wadena loam, 0 to 2 percent slopes"|"411275"\n'
                '"L138B"|"Clarion loam, 2 to 5 percent slopes"|"2765537"\n')
            frame = read_mapunit_table(path, ["musym", "muname", "mukey"])
            self.assertEqual(list(frame.columns), ["musym", "muname", "mukey"])
            self.assertEqual(frame.loc[1, "musym"], "L138B")
            self.assertEqual(frame.loc[0, "mukey"], "411275")

    def test_rejects_row_width_mismatch(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapunit.txt"
            path.write_text('"108"|"Wadena loam"\n')
            with self.assertRaisesRegex(ValueError, "has 2 fields"):
                read_mapunit_table(path, ["musym", "muname", "mukey"])

    def test_rejects_duplicate_mukey(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapunit.txt"
            path.write_text('"A"|"one"|"411275"\n"B"|"two"|"411275"\n')
            with self.assertRaisesRegex(ValueError, "duplicate mukey"):
                read_mapunit_table(path, ["musym", "muname", "mukey"])


class ArchiveValidationTest(unittest.TestCase):
    def test_accepts_archive_with_all_required_members(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ARCHIVE_NAME
            make_zip(path, valid_members())
            assignment_module._validate_archive(path)

    def test_rejects_missing_required_member(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ARCHIVE_NAME
            members = valid_members()
            del members["IA169/tabular/mstabcol.txt"]
            make_zip(path, members)
            with self.assertRaisesRegex(ValueError, "missing required"):
                assignment_module._validate_archive(path)

    def test_rejects_corrupt_member_via_testzip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ARCHIVE_NAME
            members = valid_members()
            members["IA169/tabular/mapunit.txt"] = b"UNIQUE_MARKER_DATA"
            make_zip(path, members)
            blob = bytearray(path.read_bytes())
            marker = bytes(blob).find(b"UNIQUE_MARKER_DATA")
            self.assertGreaterEqual(marker, 0)
            blob[marker] ^= 0xFF
            path.write_bytes(bytes(blob))
            with self.assertRaisesRegex(ValueError, "corrupt archive member"):
                assignment_module._validate_archive(path)

    def test_rejects_not_a_zip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ARCHIVE_NAME
            path.write_bytes(b"not a zip archive")
            with self.assertRaises(zipfile.BadZipFile):
                assignment_module._validate_archive(path)

    def test_corrupt_cache_is_replaced_by_download(self):
        with TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            path = raw_dir / ARCHIVE_NAME
            path.write_bytes(b"corrupt")
            good = valid_members()

            def make_good_zip(path):
                make_zip(path, good)

            def fake_download(url, target, expected_sha256=None):
                make_good_zip(target)
                return sha256_file(target)

            with mock.patch.object(assignment_module, "download_atomic",
                                   fake_download):
                result, digest, retrieved, cached = (
                    assignment_module._acquire_archive(raw_dir))
            self.assertEqual(result, path)
            self.assertFalse(cached)
            self.assertIsInstance(retrieved, str)
            self.assertEqual(digest, sha256_file(path))
            assignment_module._validate_archive(path)

    def test_valid_cache_is_kept_without_network(self):
        with TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            path = raw_dir / ARCHIVE_NAME
            make_zip(path, valid_members())

            def unexpected_download(*args, **kwargs):
                raise AssertionError("network must not be used for valid cache")

            with mock.patch.object(assignment_module, "download_atomic",
                                   unexpected_download):
                result, digest, retrieved, cached = (
                    assignment_module._acquire_archive(raw_dir))
            self.assertEqual(result, path)
            self.assertTrue(cached)
            self.assertEqual(digest, sha256_file(path))
            self.assertIsInstance(retrieved, str)


class ExtractionTest(unittest.TestCase):
    def test_replaces_incomplete_extraction(self):
        with TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / ARCHIVE_NAME
            make_zip(zip_path, valid_members())
            extract_dir = Path(tmp) / "IA169"
            assignment_module._ensure_extracted(zip_path, extract_dir)
            first = extract_dir / "IA169/tabular/mapunit.txt"
            self.assertTrue(first.is_file())
            first.unlink()
            assignment_module._ensure_extracted(zip_path, extract_dir)
            self.assertTrue(first.is_file())
            self.assertEqual(first.read_bytes(), b"payload")


class ExtractionFreshnessTest(unittest.TestCase):
    SPATIAL_SUFFIXES = (".dbf", ".prj", ".shp", ".shx")

    def _write_ssurgo_zip(self, path: Path, muname: str) -> None:
        spatial = path.parent / "_spatial_build"
        spatial.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"MUKEY": ["123456"],
             "geometry": [box(-93.7, 41.9, -93.5, 42.1)]},
            crs=4326,
        ).to_file(spatial / "soilmu_a_ia169.shp")
        members = {
            "IA169/tabular/mstabcol.txt": MAPUNIT_METADATA.encode(),
            "IA169/tabular/mapunit.txt":
                f'"L1"|"{muname}"|"123456"\n'.encode(),
        }
        for suffix in self.SPATIAL_SUFFIXES:
            member = f"IA169/spatial/soilmu_a_ia169{suffix}"
            members[member] = (spatial / f"soilmu_a_ia169{suffix}").read_bytes()
        make_zip(path, members)

    def _write_fields(self, path: Path) -> None:
        rows = []
        for number in range(1, 26):
            geometry = (box(-93.7, 41.9, -93.5, 42.1) if number == 1
                        else box(0, 0, 0.001, 0.001))
            rows.append({"field_id": f"STORY-{number:02d}",
                         "geometry": geometry})
        gpd.GeoDataFrame(rows, crs=4326).to_file(path, driver="GeoJSON")

    def test_fresh_archive_forces_replacement_of_stale_extraction(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ssurgo_dir = root / "ssurgo"
            extract_dir = ssurgo_dir / "IA169"
            stale_zip = root / "stale.zip"
            self._write_ssurgo_zip(stale_zip, "Stale loam")
            with zipfile.ZipFile(stale_zip) as archive:
                for member in REQUIRED_MEMBERS:
                    archive.extract(member, extract_dir)
            zip_path = ssurgo_dir / ARCHIVE_NAME
            self._write_ssurgo_zip(zip_path, "Fresh loam")
            fields_path = root / "fields.geojson"
            self._write_fields(fields_path)
            output_dir = root / "out"
            provenance_dir = root / "prov"
            with mock.patch.object(
                    assignment_module, "_acquire_archive",
                    return_value=(zip_path, "d" * 64,
                                  "2026-01-01T00:00:00+00:00", False)):
                assignment_module.build_field_soil_mapping(
                    root, fields_path, output_dir, provenance_dir)
            extracted = (extract_dir / "IA169/tabular/mapunit.txt"
                         ).read_text()
            self.assertIn("Fresh loam", extracted)
            self.assertNotIn("Stale loam", extracted)

    def test_complete_extraction_is_reused_when_not_forced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = root / ARCHIVE_NAME
            make_zip(zip_path, valid_members())
            extract_dir = root / "IA169"
            assignment_module._ensure_extracted(zip_path, extract_dir)
            original = (extract_dir / "IA169/tabular/mapunit.txt"
                        ).read_bytes()
            make_zip(zip_path, {name: b"DIFFERENT"
                                for name in REQUIRED_MEMBERS})
            assignment_module._ensure_extracted(zip_path, extract_dir)
            self.assertEqual(
                (extract_dir / "IA169/tabular/mapunit.txt").read_bytes(),
                original)


class CommittedOutputTest(unittest.TestCase):
    OVERLAP = Path("data/processed/assignment-04/field_soil_overlap.csv")
    SOILS = Path("data/processed/assignment-04/soil_map_units.geojson")
    PROVENANCE = Path("data/provenance/ssurgo_ia169.json")
    PNG = Path("docs/assets/field_spatial_map.png")

    def test_overlap_csv_contract(self):
        rows = pd.read_csv(self.OVERLAP, dtype={"mukey": str})
        self.assertEqual(list(rows.columns), [
            "field_id", "mukey", "musym", "muname", "overlap_area_m2",
            "field_area_m2", "field_fraction",
        ])
        self.assertEqual(rows["field_id"].nunique(), 25)
        self.assertEqual(set(rows["field_id"]),
                         {f"STORY-{number:02d}" for number in range(1, 26)})
        self.assertTrue(rows["field_fraction"].between(0.0, 1.0).all())
        self.assertTrue((rows["overlap_area_m2"] >= 0).all())
        self.assertTrue((rows["field_area_m2"] > 0).all())
        keys = rows[["field_id", "mukey"]].values.tolist()
        self.assertEqual(keys, sorted(keys))
        self.assertFalse(rows.duplicated(["field_id", "mukey"]).any())
        zero = rows.loc[rows["mukey"] == ""]
        self.assertTrue((zero["overlap_area_m2"] == 0).all())
        self.assertTrue((zero["field_fraction"] == 0).all())

    def test_soil_geojson_contract(self):
        soils = gpd.read_file(self.SOILS)
        self.assertEqual(soils.crs.to_epsg(), 4326)
        self.assertEqual(set(soils.columns),
                         {"mukey", "musym", "muname", "geometry"})
        self.assertTrue(soils["mukey"].is_unique)
        self.assertTrue(soils["mukey"].str.len().gt(0).all())
        self.assertTrue(soils["muname"].str.len().gt(0).all())
        rows = pd.read_csv(self.OVERLAP, dtype={"mukey": str})
        self.assertEqual(set(rows.loc[rows["mukey"] != "", "mukey"]),
                         set(soils["mukey"]))

    def test_provenance_contract(self):
        manifest = json.loads(self.PROVENANCE.read_text())
        self.assertEqual(manifest["snapshot_date"], "2025-09-09")
        self.assertEqual(
            manifest["archive_name"], ARCHIVE_NAME)
        self.assertEqual(manifest["source_urls"], [
            "https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/"
            "wss_SSA_IA169_%5B2025-09-09%5D.zip"])
        self.assertEqual(manifest["source_crs"], "EPSG:4326")
        self.assertEqual(manifest["analysis_crs"], "EPSG:5070")
        self.assertEqual(manifest["output_crs"], "EPSG:4326")
        self.assertEqual(manifest["producer"], "scripts/assignment_04.py")
        digest = list(manifest["sha256"].values())[0]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertIn("USDA Natural Resources Conservation Service",
                      manifest["source_organization"])
        self.assertIn("1:12,000 to 1:63,360", manifest["license_note"])
        counts = manifest["counts"]
        self.assertEqual(counts["fields"], 25)
        self.assertGreater(counts["archive_members"], 0)
        self.assertEqual(counts["mapunit_table_rows"],
                         counts["unique_mapunits"])
        self.assertGreater(counts["overlapping_mapunits"], 0)
        self.assertGreater(counts["overlap_rows"], 0)
        self.assertEqual(counts["soil_features"], counts["overlapping_mapunits"])
        self.assertGreaterEqual(counts["csv_rows"], 25)

    def test_png_contract(self):
        self.assertTrue(self.PNG.is_file())
        self.assertGreater(self.PNG.stat().st_size, 1000)
        data = self.PNG.read_bytes()
        marker = data.find(b"pHYs")
        self.assertGreaterEqual(marker, 0)
        pixels_per_meter = int.from_bytes(
            data[marker + 4: marker + 8], "big")
        self.assertAlmostEqual(pixels_per_meter * 0.0254, 160, delta=0.5)


if __name__ == "__main__":
    unittest.main()
