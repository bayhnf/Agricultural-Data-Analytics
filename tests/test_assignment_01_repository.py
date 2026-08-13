import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class Assignment01RepositoryTest(unittest.TestCase):
    def test_required_setup_files_and_mermaid_exist(self):
        for relative in (
            ".gitignore",
            ".python-version",
            "requirements.txt",
            "README.md",
            "docs/reports/assignment-01-evidence.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("```mermaid", readme)
        self.assertIn("Assignment 1", readme)

    def test_private_paths_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        for pattern in (".env", ".venv/", "data/raw/", "*.zip", "*.tif"):
            self.assertIn(pattern, ignored)


if __name__ == "__main__":
    unittest.main()
