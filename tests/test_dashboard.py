"""Contract tests for the Task 11 dashboard and the final project."""

import contextlib
import io
import json
import math
import pathlib
import re
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser

import scripts.build_dashboard as build_dashboard
import scripts.verify_repository as verify_repository


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
EXPECTED_KEYS = KPI_KEYS | {"sources", "fields"}
SOURCE_NAMES = frozenset({"fields", "crops", "ndvi", "weather", "soil",
                          "units"})
NUMERIC_KEYS = KPI_KEYS - {"dominant_crop_2023", "scene_date"}
REQUIRED_IMAGES = frozenset({
    "assets/field_area_distribution.png",
    "assets/crop_mix_2023.png",
    "assets/crop_rotation_patterns.png",
    "assets/field_spatial_map.png",
    "assets/ndvi_map.png",
    "assets/weather_trends.png",
    "assets/integrated_spatial_analysis.png",
    "assets/soil_health_metrics.png",
})
SECTION_IDS = ("fields", "vegetation", "weather", "integration", "soil",
               "methods", "limitations", "provenance")
FIELD_SCHEMA = (
    "field_id",
    "area_ha",
    "crop_2023",
    "crop_2023_pixels",
    "soil_type",
    "soil_name",
    "mean_ndvi",
    "ndvi_coverage_fraction",
    "organic_matter_pct",
    "ph_h2o",
    "cec_cmol_kg",
    "carbon_storage_mg_c_ha",
)
FIELD_NUMERIC = frozenset(FIELD_SCHEMA) - {"field_id", "crop_2023",
                                           "soil_type", "soil_name"}


def write_minimal_inputs(root: pathlib.Path) -> None:
    """Write synthetic Assignment 2-8 products under root."""
    base = root / "data/processed"
    for name in ("assignment-02", "assignment-05", "assignment-06",
                 "assignment-07", "assignment-08"):
        (base / name).mkdir(parents=True, exist_ok=True)

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

    features = []
    for index in range(1, 26):
        features.append({
            "type": "Feature",
            "properties": {
                "field_id": f"STORY-{index:02d}",
                "area_ha": index * 1.0,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                                 [0.0, 1.0], [0.0, 0.0]]],
            },
        })
    (base / "assignment-02" / "fields_EPSG4326.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}) + "\n",
        encoding="utf-8")

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
    integration_rows = [
        "field_id,crop_2023_name,dominant_soil,dominant_soil_name,"
        "dominant_soil_mukey,dominant_soil_overlap_area_ha,mean_ndvi,"
        "valid_pixel_count,total_pixel_count,ndvi_coverage_fraction",
    ]
    for index in range(1, 26):
        name = "Corn" if index % 2 else "Soybeans"
        code = 388 if index % 2 else 95
        integration_rows.append(
            f"STORY-{index:02d},{name},{code},\"Test soil {index}\",4113{index:02d},"
            f"{index * 1.5:.2f},0.8,{index * 10},{index * 10},1.0")
    (base / "assignment-07" / "integrated_field_summary.csv").write_text(
        "\n".join(integration_rows) + "\n", encoding="utf-8")
    soil_rows = [
        "field_id,organic_matter_pct,ph_h2o,cec_cmol_kg,erosion_k_factor,"
        "carbon_storage_mg_c_ha,soil_coverage_fraction,om_coverage_fraction,"
        "ph_coverage_fraction,cec_coverage_fraction,erosion_coverage_fraction,"
        "carbon_coverage_fraction",
    ]
    for index in range(1, 26):
        soil_rows.append(
            f"STORY-{index:02d},{2.0 + index * 0.1:.2f},6.5,20.0,0.28,"
            f"{index * 5.0:.2f},1.0,1.0,1.0,1.0,1.0,1.0")
    (base / "assignment-08" / "soil_health_by_field.csv").write_text(
        "\n".join(soil_rows) + "\n", encoding="utf-8")
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

    def test_rejects_duplicate_integration_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            integration_path = (root / "data/processed/assignment-07"
                                / "integrated_field_summary.csv")
            lines = integration_path.read_text(encoding="utf-8").splitlines()
            lines.append(lines[1])
            integration_path.write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_rejects_geojson_missing_area_ha(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            geojson_path = (root / "data/processed/assignment-02"
                            / "fields_EPSG4326.geojson")
            document = json.loads(geojson_path.read_text(encoding="utf-8"))
            del document["features"][0]["properties"]["area_ha"]
            geojson_path.write_text(json.dumps(document) + "\n",
                                    encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_rejects_non_integral_crop_valid_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            crops_path = (root / "data/processed/assignment-02"
                          / "cdl_EPSG4326.csv")
            lines = crops_path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace("0.9,1.0,10,10", "0.9,1.0,10.5,10", 1)
            crops_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_fields_records_match_spec_schema_sorted_and_finite(self):
        payload = build_dashboard.build_payload(ROOT)
        fields = payload["fields"]
        self.assertEqual(len(fields), 25)
        ids = [record["field_id"] for record in fields]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 25)
        for record in fields:
            self.assertEqual(tuple(record), FIELD_SCHEMA, record["field_id"])
            for key in FIELD_NUMERIC:
                self.assertTrue(math.isfinite(float(record[key])),
                                f"{record['field_id']}.{key}")
            self.assertTrue(record["field_id"])
            self.assertTrue(record["crop_2023"])
            self.assertTrue(record["soil_type"])
            self.assertTrue(record["soil_name"])
        by_id = {record["field_id"]: record for record in fields}
        self.assertIn("STORY-01", by_id)
        self.assertIn("STORY-25", by_id)

    def test_fields_ids_match_across_every_input(self):
        payload = build_dashboard.build_payload(ROOT)
        expected = {f"STORY-{index:02d}" for index in range(1, 26)}
        self.assertEqual({record["field_id"] for record in payload["fields"]},
                         expected)

    def test_rejects_cross_source_field_id_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            ndvi_path = (root / "data/processed/assignment-05"
                         / "field_ndvi.csv")
            lines = ndvi_path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace("STORY-01", "STORY-99", 1)
            ndvi_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_rejects_non_finite_field_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_minimal_inputs(root)
            soil_path = (root / "data/processed/assignment-08"
                         / "soil_health_by_field.csv")
            lines = soil_path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace(",6.5,", ",inf,", 1)
            soil_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_dashboard.build_payload(root)

    def test_fields_payload_is_deterministic(self):
        first = build_dashboard.build_payload(ROOT)["fields"]
        second = build_dashboard.build_payload(ROOT)["fields"]
        self.assertEqual(first, second)


def run_git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1_count = 0
        self.nav_count = 0
        self.main_ids: list[str] = []
        self.ids: list[str] = []
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []
        self.stylesheets: list[str] = []
        self.scripts: list[str | None] = []
        self.dashboard: list[str] = []
        self.kpi: dict[str, list[str]] = {}
        self.text: list[str] = []
        self._stack: list[tuple[str, str | None, int | None]] = []

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        if tag == "nav":
            self.nav_count += 1
        if tag == "main" and values.get("id"):
            self.main_ids.append(values["id"])
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "img":
            self.images.append(values)
        if tag == "link" and "stylesheet" in values.get("rel", "").lower():
            self.stylesheets.append(values.get("href", ""))
        if tag == "script":
            self.scripts.append(values.get("src"))
        if values.get("data-dashboard"):
            self.dashboard.append(values["data-dashboard"])
        key = values.get("data-kpi")
        index = None
        if key:
            self.kpi.setdefault(key, [])
            self.kpi[key].append("")
            index = len(self.kpi[key]) - 1
        self._stack.append((tag, key, index))

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        for _, key, index in reversed(self._stack):
            if key is not None and index is not None:
                self.kpi[key][index] += data
                break

    def handle_endtag(self, tag: str) -> None:
        while self._stack:
            item = self._stack.pop()
            if item[0] == tag:
                break

    @property
    def page_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text)).strip()


def parse_page() -> PageParser:
    parser = PageParser()
    parser.feed((ROOT / "docs/index.html").read_text(encoding="utf-8"))
    return parser


class LedeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lede_text: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "p" and "lede" in (values.get("class") or "").split():
            self._depth = 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.lede_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._depth:
            self._depth = 0


class ControlsParser(HTMLParser):
    """Collect labels, selects, buttons, and live regions."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: dict[str, str] = {}
        self.selects: list[dict[str, object]] = []
        self.buttons: list[dict[str, object]] = []
        self.live_regions: list[dict[str, str | None]] = []
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._button_text: list[str] = []

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "label" and values.get("for"):
            self._label_for = values["for"]
            self._label_text = []
        if tag == "select":
            self.selects.append({
                "id": values.get("id"),
                "disabled": values.get("disabled") is not None
                            or "disabled" in values,
                "name": values.get("name"),
            })
        if tag == "button" or (tag == "input"
                               and values.get("type") == "reset"):
            self.buttons.append({"text": "", "type": values.get("type")})
            self._button_text = []
        if values.get("aria-live"):
            self.live_regions.append({
                "id": values.get("id"),
                "aria-live": values.get("aria-live"),
            })

    def handle_data(self, data: str) -> None:
        if self._label_for is not None:
            self._label_text.append(data)
        if self.buttons:
            self._button_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_for is not None:
            self.labels[self._label_for] = " ".join(self._label_text).strip()
            self._label_for = None
        if tag == "button" and self.buttons:
            self.buttons[-1]["text"] = " ".join(self._button_text).strip()
            self._button_text = []


def parse_controls() -> ControlsParser:
    parser = ControlsParser()
    parser.feed((ROOT / "docs/index.html").read_text(encoding="utf-8"))
    return parser


class RepositoryVerifierTest(unittest.TestCase):
    def test_untracked_secrets_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            (root / "secrets.env").write_text(
                "GITHUB_TOKEN=ghp_" + "A" * 36 + "\n", encoding="utf-8")
            (root / "public.txt").write_text("public data\n",
                                             encoding="utf-8")
            run_git(root, "add", "public.txt")
            result = verify_repository.verify(root)
            self.assertEqual(result.tracked_count, 1)
            self.assertEqual(result.findings, [])

    def test_tracked_secret_rejected_without_echoing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            secret = "ghp_" + "A" * 36
            (root / "creds.json").write_text(
                '{"token": "%s"}\n' % secret, encoding="utf-8")
            run_git(root, "add", "creds.json")
            result = verify_repository.verify(root)
            self.assertTrue(result.findings)
            self.assertNotIn(secret, "\n".join(result.findings))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = verify_repository.main(root=root)
            self.assertEqual(code, 1)
            self.assertNotIn(secret, output.getvalue())
            self.assertIn("creds.json", output.getvalue())

    def test_rule_documentation_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            (root / "docs").mkdir()
            (root / "docs/scanner-rules.md").write_text(
                "The scanner rejects: .env files, ghp_, github_pat_, "
                "GOCSPX-, refresh_token, client_secret, Classroom archives, "
                "OAuth tokens, and private source ZIPs.\n", encoding="utf-8")
            run_git(root, "add", "docs/scanner-rules.md")
            result = verify_repository.verify(root)
            self.assertEqual(result.findings, [])

    def test_oversized_tracked_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            with (root / "big.bin").open("wb") as stream:
                stream.truncate(10 * 1024 * 1024 + 1)
            run_git(root, "add", "big.bin")
            result = verify_repository.verify(root)
            self.assertTrue(any("big.bin" in finding
                                for finding in result.findings))
            self.assertTrue(any("size" in finding.lower()
                                for finding in result.findings))

    def test_forbidden_tracked_filenames_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            for name in ("secrets.env", "classroom-archive.txt",
                         "oauth_config.json", "access_token.txt",
                         "course-private.zip"):
                (root / name).write_text("placeholder\n", encoding="utf-8")
            run_git(root, "add", ".")
            result = verify_repository.verify(root)
            self.assertEqual(len(result.findings), 5)
            combined = "\n".join(result.findings)
            self.assertIn(".env", combined)
            self.assertIn("Classroom", combined)
            self.assertIn("OAuth", combined)
            self.assertIn("token", combined)
            self.assertIn("ZIP", combined)

    def test_missing_local_html_references_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            (root / "docs").mkdir()
            (root / "docs/index.html").write_text(
                "<!doctype html><html><head>"
                '<link rel="stylesheet" href="styles.css">'
                "</head><body>"
                '<img src="assets/missing.png" alt="missing image">'
                '<script src="app.js"></script>'
                '<a href="data/dashboard.json">data</a>'
                '<img src="https://example.com/x.png" alt="external">'
                '<a href="#top">top</a>'
                '<a href="mailto:test@example.com">mail</a>'
                '<img src="data:image/png;base64,AAAA" alt="inline">'
                "</body></html>\n", encoding="utf-8")
            run_git(root, "add", "docs/index.html")
            result = verify_repository.verify(root)
            self.assertEqual(result.reference_count, 4)
            self.assertEqual(len(result.findings), 4)
            combined = "\n".join(result.findings)
            for missing in ("styles.css", "assets/missing.png", "app.js",
                            "data/dashboard.json"):
                self.assertIn(missing, combined, missing)

    def test_unquoted_assigned_secrets_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            token_value = "abcdefgh1234"
            secret_value = "opaquestring"
            (root / "config.ini").write_text(
                "refresh_token: %s\n"
                "client_secret = %s\n" % (token_value, secret_value),
                encoding="utf-8")
            run_git(root, "add", "config.ini")
            result = verify_repository.verify(root)
            self.assertTrue(result.findings)
            combined = "\n".join(result.findings)
            self.assertNotIn(token_value, combined)
            self.assertNotIn(secret_value, combined)
            self.assertIn("refresh_token", combined)
            self.assertIn("client_secret", combined)

    def test_real_repository_verifies_clean(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = verify_repository.main(root=ROOT)
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("tracked files", text)
        self.assertIn("references", text)

    def test_tracked_machine_local_absolute_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run_git(root, "init", "-q")
            leaked = "/" + "home/" + "alice/projects/sample/docs/assets/field.png"
            (root / "artifact.md").write_text(
                f"wrote {leaked}\n",
                encoding="utf-8")
            run_git(root, "add", "artifact.md")
            result = verify_repository.verify(root)
            self.assertTrue(result.findings)
            combined = "\n".join(result.findings)
            self.assertIn("machine-local absolute path", combined)
            self.assertNotIn(leaked, combined)

    def test_real_repository_notebook_output_has_no_machine_path(self):
        notebook = ROOT / "notebooks/04_field_mapping.ipynb"
        self.assertNotRegex(
            notebook.read_text(encoding="utf-8"),
            r"wrote /(?:home|Users)/",
        )


class DashboardPageTest(unittest.TestCase):
    def test_page_structure_and_accessibility(self):
        parser = parse_page()
        self.assertEqual(parser.h1_count, 1)
        self.assertIn("main", parser.main_ids)
        self.assertIn("#main", parser.links)
        self.assertGreaterEqual(parser.nav_count, 1)
        self.assertGreaterEqual(len(parser.scripts), 1)
        for section in SECTION_IDS:
            self.assertIn(section, parser.ids, section)

    def test_required_images_have_alt_and_dimensions(self):
        parser = parse_page()
        srcs = {image.get("src") for image in parser.images}
        self.assertGreaterEqual(len(parser.images), 7)
        self.assertTrue(REQUIRED_IMAGES <= srcs)
        for image in parser.images:
            self.assertTrue(image.get("alt", "").strip(), image.get("src"))
        for image in parser.images:
            if image.get("src") in REQUIRED_IMAGES:
                self.assertTrue(image.get("width") and image.get("height"),
                                image.get("src"))
        for src in srcs:
            if src and not src.startswith(("http:", "https:", "//", "data:",
                                           "#", "mailto:")):
                self.assertTrue((ROOT / "docs" / src).is_file(), src)

    def test_stylesheet_and_json_references_resolve(self):
        parser = parse_page()
        self.assertGreaterEqual(len(parser.stylesheets), 1)
        for href in parser.stylesheets:
            self.assertTrue((ROOT / "docs" / href).is_file(), href)
        self.assertEqual(parser.dashboard, ["data/dashboard.json"])
        self.assertTrue((ROOT / "docs/data/dashboard.json").is_file())
        self.assertTrue((ROOT / "docs/styles.css").is_file())

    def test_kpi_bindings_present_once_and_not_hardcoded(self):
        parser = parse_page()
        self.assertEqual(set(parser.kpi), KPI_KEYS)
        for key, values in parser.kpi.items():
            self.assertEqual(len(values), 1, key)
            self.assertIn(values[0].strip(), ("", "\u2014"), key)

    def test_required_attribution_and_limitation_copy(self):
        text = parse_page().page_text
        for phrase in (
            "Contains modified Copernicus Sentinel data 2023",
            "not current ownership or program boundaries",
            "not station observations",
            "ceiling values and not precise rankings",
            "not measured field samples",
            "carbon-credit estimates",
            "farm recommendations",
            "K-factor",
            "least-complete coverage",
            "USDA ARS ACPF",
            "USDA NASS CDL",
            "Sentinel-2",
            "Element 84",
            "NASA POWER",
            "USDA NRCS SSURGO",
            "Census",
        ):
            self.assertIn(phrase, text, phrase)

    def test_lede_has_no_hardcoded_kpi_values(self):
        parser = LedeParser()
        parser.feed((ROOT / "docs/index.html").read_text(encoding="utf-8"))
        lede = re.sub(r"\s+", " ", " ".join(parser.lede_text)).strip()
        self.assertIn("Story County, Iowa", lede)
        self.assertNotRegex(lede, r"\b25\b")
        self.assertNotIn("June 20, 2023", lede)
        self.assertNotIn("2023-06-20", lede)

    def test_css_focus_styling_and_mobile_breakpoint(self):
        css = (ROOT / "docs/styles.css").read_text(encoding="utf-8")
        self.assertIn(":focus-visible", css)
        self.assertIn(":focus", css)
        self.assertTrue(re.search(r"@media[^{]*max-width", css))
        self.assertIn("prefers-reduced-motion", css)

    def test_filter_selects_disabled_with_labels(self):
        parser = parse_controls()
        select_ids = [select["id"] for select in parser.selects]
        self.assertIn("field-id-filter", select_ids)
        self.assertIn("soil-type-filter", select_ids)
        for select in parser.selects:
            if select["id"] in ("field-id-filter", "soil-type-filter"):
                self.assertTrue(select["disabled"], select["id"])
                label = parser.labels.get(str(select["id"]), "")
                self.assertTrue(label, select["id"])
        self.assertIn("Field ID", parser.labels.get("field-id-filter", ""))
        self.assertIn("Soil Type", parser.labels.get("soil-type-filter", ""))

    def test_reset_control_present(self):
        parser = parse_controls()
        self.assertTrue(any(
            button.get("type") == "reset"
            or "reset" in str(button.get("text", "")).lower()
            for button in parser.buttons))

    def test_polite_live_narrative_region(self):
        parser = parse_controls()
        self.assertTrue(any(
            region["aria-live"] == "polite"
            and "narrative" in str(region.get("id", "")).lower()
            for region in parser.live_regions))

    def test_ndvi_narrative_bands_and_scouting_copy_locked(self):
        source = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]+src="([^"]+)"', source):
            source += "\n" + (ROOT / "docs" / src).read_text(encoding="utf-8")
        text = re.sub(r"\s+", " ", source)
        self.assertIn("0.3", text)
        self.assertIn("0.6", text)
        self.assertIn("immediate scouting", text)
        self.assertRegex(text,
                         r"scene[^.<]{0,80}cannot confirm")

    def test_rotation_figure_has_alt_and_source(self):
        parser = parse_page()
        rotations = [image for image in parser.images
                     if image.get("src") == "assets/crop_rotation_patterns.png"]
        self.assertEqual(len(rotations), 1)
        self.assertTrue(rotations[0].get("alt", "").strip())
        self.assertTrue(rotations[0].get("width")
                        and rotations[0].get("height"))


class FinalProjectDocsTest(unittest.TestCase):
    def test_readme_documents_final_project(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("feature/final-project-dashboard", readme)
        self.assertIn("github.io", readme)
        self.assertIn("AI_DOCS", readme)
        self.assertIn("python -m http.server", readme)
        self.assertIn("build_dashboard", readme)
        self.assertNotIn("feature/final-dashboard` | Final project",
                         readme)

    def test_ai_docs_summarizes_ai_usage(self):
        ai_docs = (ROOT / "docs/AI_DOCS.md").read_text(encoding="utf-8")
        lowered = ai_docs.lower()
        for phrase in ("generated", "verified", "review",
                       "did not", "public data"):
            self.assertIn(phrase, lowered, phrase)
        self.assertNotRegex(ai_docs, r"ghp_|github_pat_|GOCSPX-")


if __name__ == "__main__":
    unittest.main()
