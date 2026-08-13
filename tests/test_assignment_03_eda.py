import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class Assignment03Test(unittest.TestCase):
    def test_notebook_and_three_figures_exist(self):
        notebook = ROOT / "notebooks/03_field_eda.ipynb"
        self.assertTrue(notebook.is_file())
        document = json.loads(notebook.read_text())
        joined = "\n".join(
            "".join(cell.get("source", [])) for cell in document["cells"]
        )
        for phrase in ("area_ha", "crop_2023_name", "rotation"):
            self.assertIn(phrase, joined)
        for name in (
            "field_area_distribution.png",
            "crop_mix_2023.png",
            "crop_rotation_patterns.png",
        ):
            self.assertGreater((ROOT / "docs/assets" / name).stat().st_size, 1000)
