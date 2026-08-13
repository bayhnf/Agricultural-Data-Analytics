"""Contract tests for the Task 11 dashboard (slices A and B)."""

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
EXPECTED_KEYS = KPI_KEYS | {"sources"}
SOURCE_NAMES = frozenset({"fields", "crops", "ndvi", "weather", "soil",
                          "units"})
NUMERIC_KEYS = KPI_KEYS - {"dominant_crop_2023", "scene_date"}
REQUIRED_IMAGES = frozenset({
    "assets/field_area_distribution.png",
    "assets/crop_mix_2023.png",
    "assets/field_spatial_map.png",
    "assets/ndvi_map.png",
    "assets/weather_trends.png",
    "assets/integrated_spatial_analysis.png",
    "assets/soil_health_metrics.png",
})
SECTION_IDS = ("fields", "vegetation", "weather", "integration", "soil",
               "methods", "limitations", "provenance")


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

    def test_real_repository_verifies_clean(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = verify_repository.main(root=ROOT)
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("tracked files", text)
        self.assertIn("references", text)


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

    def test_css_focus_styling_and_mobile_breakpoint(self):
        css = (ROOT / "docs/styles.css").read_text(encoding="utf-8")
        self.assertIn(":focus-visible", css)
        self.assertIn(":focus", css)
        self.assertTrue(re.search(r"@media[^{]*max-width", css))
        self.assertIn("prefers-reduced-motion", css)


if __name__ == "__main__":
    unittest.main()
