import unittest

import geopandas as gpd
from shapely.geometry import box

from scripts.assignment_02 import COUNTY_QUERY, select_grid_fields


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

    def test_committed_field_contract(self):
        path = "data/processed/assignment-02/fields_EPSG4326.geojson"
        fields = gpd.read_file(path)
        self.assertEqual(len(fields), 25)
        self.assertEqual(fields.crs.to_epsg(), 4326)
        self.assertEqual(fields["field_id"].nunique(), 25)
        self.assertTrue((fields["inside_fraction"] >= 0.95).all())
        self.assertTrue((fields["area_ha"] > 0).all())


class CountyQueryTest(unittest.TestCase):
    def test_geoid_is_a_quoted_string_in_tigerweb_query(self):
        self.assertEqual(COUNTY_QUERY["where"], "GEOID='19169'")


if __name__ == "__main__":
    unittest.main()
