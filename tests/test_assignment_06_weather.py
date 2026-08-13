import json
import math
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import scripts.assignment_06 as assignment_06

from scripts.assignment_06 import (
    analyze_weather,
    build_weather_analysis,
    parse_power_daily,
    power_request_params,
)


ROOT = pathlib.Path(__file__).parents[1]


def make_payload(dates, temperatures, precipitation):
    return {
        "properties": {
            "parameter": {
                "T2M": dict(zip(dates, temperatures)),
                "PRECTOTCORR": dict(zip(dates, precipitation)),
            }
        }
    }


def full_payload(start="1991-01-01", end="2023-12-31"):
    dates = pd.date_range(start, end, freq="D")
    return make_payload(
        [date.strftime("%Y%m%d") for date in dates],
        [10.0 if date.year <= 2020 else 12.0 for date in dates],
        [1.0 for _ in dates],
    )


class PowerRequestTest(unittest.TestCase):
    def test_request_is_one_bounded_daily_point_query(self):
        self.assertEqual(
            power_request_params(-93.454655, 42.037083),
            {
                "parameters": "T2M,PRECTOTCORR",
                "community": "AG",
                "longitude": -93.454655,
                "latitude": 42.037083,
                "start": "19910101",
                "end": "20231231",
                "format": "JSON",
            },
        )


class PowerParserTest(unittest.TestCase):
    def test_parses_sorted_dates_and_converts_fill_values_to_null(self):
        payload = make_payload(
            ["20230102", "20230101"],
            [-999.0, 1.0],
            [0.0, 2.5],
        )
        frame = parse_power_daily(payload)
        self.assertEqual(
            list(frame.columns), ["date", "t2m_c", "precip_mm"])
        self.assertEqual(
            frame["date"].tolist(),
            [pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02")],
        )
        self.assertEqual(frame.loc[0, "precip_mm"], 2.5)
        self.assertTrue(math.isnan(frame.loc[1, "t2m_c"]))

    def test_requires_both_parameters_with_matching_date_keys(self):
        payload = {"properties": {"parameter": {
            "T2M": {"20230101": 1.0},
        }}}
        with self.assertRaisesRegex(ValueError, "PRECTOTCORR"):
            parse_power_daily(payload)

        payload = {"properties": {"parameter": {
            "T2M": {"20230101": 1.0, "20230102": 2.0},
            "PRECTOTCORR": {"20230101": 0.0, "20230103": 1.0},
        }}}
        with self.assertRaisesRegex(ValueError, "date keys"):
            parse_power_daily(payload)

    def test_rejects_invalid_date_keys_and_gaps(self):
        for key in ("2023-01-01", "2023010", "202301011"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
                    parse_power_daily(make_payload([key], [1.0], [0.0]))
        for key in ("20230230", "20231301"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, key):
                    parse_power_daily(make_payload([key], [1.0], [0.0]))
        with self.assertRaisesRegex(ValueError, "continuous"):
            parse_power_daily(make_payload(
                ["20230101", "20230103"], [1.0, 2.0], [0.0, 1.0]))

    def test_rejects_invalid_values_and_negative_precipitation(self):
        for bad in (None, "1.0", True, float("nan"),
                    float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "finite numeric"):
                    parse_power_daily(
                        make_payload(["20230101"], [bad], [0.0]))
        with self.assertRaisesRegex(ValueError, "negative precipitation"):
            parse_power_daily(
                make_payload(["20230101"], [1.0], [-0.5]))

        frame = parse_power_daily(
            make_payload(["20230101"], [1.0], [-999.0]))
        self.assertTrue(math.isnan(frame.loc[0, "precip_mm"]))


class WeatherAnalysisTest(unittest.TestCase):
    def test_centered_seven_day_temperature_mean(self):
        daily = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=9, freq="D"),
            "t2m_c": [float(day) for day in range(9)],
            "precip_mm": 0.0,
        })
        result = analyze_weather(daily)
        self.assertTrue(math.isnan(result.loc[2, "t2m_7d_c"]))
        self.assertEqual(result.loc[3, "t2m_7d_c"], 3.0)
        self.assertEqual(result.loc[5, "t2m_7d_c"], 5.0)
        self.assertTrue(math.isnan(result.loc[6, "t2m_7d_c"]))

    def test_calendar_day_keeps_february_29_and_aligns_march_1(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime([
                "2020-02-28", "2020-02-29", "2020-03-01",
                "2020-12-31", "2021-02-28", "2021-03-01",
                "2021-12-31",
            ]),
            "t2m_c": 1.0,
            "precip_mm": 0.0,
        })
        result = analyze_weather(daily)
        self.assertEqual(
            result["day_of_year"].tolist(),
            [59, 60, 61, 366, 59, 61, 366],
        )

    def test_baseline_uses_1991_through_2020_and_anomaly_only_2023(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime([
                "1991-01-01", "2020-01-01",
                "2021-01-01", "2023-01-01",
            ]),
            "t2m_c": [1.0, 3.0, 100.0, 5.0],
            "precip_mm": 0.0,
        })
        result = analyze_weather(daily)
        self.assertEqual(result["baseline_t2m_c"].tolist(),
                         [2.0, 2.0, 2.0, 2.0])
        self.assertTrue(result.loc[:2, "t2m_anomaly_c"].isna().all())
        self.assertEqual(result.loc[3, "t2m_anomaly_c"], 3.0)

    def test_february_29_has_a_separate_baseline_bucket(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime([
                "1991-03-01", "1992-02-29",
                "2020-02-29", "2020-03-01", "2023-03-01",
            ]),
            "t2m_c": [2.0, 1.0, 3.0, 10.0, 6.0],
            "precip_mm": 0.0,
        })
        result = analyze_weather(daily)
        february_29 = result["date"].dt.strftime("%m-%d") == "02-29"
        march_1 = result["date"].dt.strftime("%m-%d") == "03-01"
        self.assertEqual(
            result.loc[february_29, "baseline_t2m_c"].tolist(), [2.0, 2.0])
        self.assertEqual(
            result.loc[march_1, "baseline_t2m_c"].tolist(), [6.0, 6.0, 6.0])
        self.assertEqual(
            result.loc[result["date"] == pd.Timestamp("2023-03-01"),
                       "t2m_anomaly_c"].item(),
            0.0,
        )


class BuildContractTest(unittest.TestCase):
    def test_full_period_writes_canonical_daily_and_summary_products(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = pathlib.Path(temporary)
            build_weather_analysis(full_payload(), output_dir)

            daily = pd.read_csv(
                output_dir / "weather_daily.csv", parse_dates=["date"])
            self.assertEqual(len(daily), 12053)
            self.assertEqual(
                list(daily.columns),
                [
                    "date", "t2m_c", "precip_mm", "t2m_7d_c",
                    "day_of_year", "baseline_t2m_c", "t2m_anomaly_c",
                ],
            )
            self.assertEqual(daily["date"].min(), pd.Timestamp("1991-01-01"))
            self.assertEqual(daily["date"].max(), pd.Timestamp("2023-12-31"))
            anomaly_dates = daily.loc[
                daily["t2m_anomaly_c"].notna(), "date"]
            self.assertEqual(len(anomaly_dates), 365)
            self.assertEqual(anomaly_dates.dt.year.unique().tolist(), [2023])
            self.assertTrue((daily["baseline_t2m_c"] == 10.0).all())
            self.assertTrue(
                (daily.loc[daily["date"].dt.year == 2023,
                           "t2m_anomaly_c"] == 2.0).all())

            summary = json.loads(
                (output_dir / "weather_summary.json").read_text())
            self.assertEqual(summary["record_count"], 12053)
            self.assertEqual(summary["t2m_anomaly_2023_c"], 2.0)
            self.assertEqual(summary["precip_2023_mm"], 365.0)

    def test_rejects_truncated_or_wrong_full_period(self):
        for start, end, message in (
            ("1991-01-01", "2023-12-30", "12,053"),
            ("1990-01-01", "2022-12-31", "1991-01-01"),
        ):
            with self.subTest(start=start, end=end):
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, message):
                        build_weather_analysis(
                            full_payload(start, end),
                            pathlib.Path(temporary),
                        )

    def test_fresh_and_cached_runs_are_byte_identical(self):
        payload = full_payload()
        retrieved = "2026-08-13T17:00:00+00:00"
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "data/raw/nasa_power.json"
            output = root / "data/processed/assignment-06"
            provenance = root / "data/provenance/nasa_power.json"
            figure = root / "docs/assets/weather.png"
            raw.parent.mkdir(parents=True)
            raw.write_text(json.dumps(payload, sort_keys=True))
            products = (
                output / "weather_daily.csv",
                output / "weather_summary.json",
                provenance,
                figure,
            )
            with (
                patch.object(assignment_06, "ROOT", root),
                patch.object(assignment_06, "RAW_CACHE_PATH", raw),
                patch.object(assignment_06, "OUTPUT_DIR", output),
                patch.object(assignment_06, "PROVENANCE_PATH", provenance),
                patch.object(assignment_06, "FIGURE_PATH", figure),
                patch.object(
                    assignment_06,
                    "fetch_power_daily",
                    side_effect=[
                        (payload, retrieved, False),
                        (payload, retrieved, True),
                    ],
                ),
            ):
                assignment_06.main()
                fresh = [
                    assignment_06.sha256_file(path) for path in products]
                assignment_06.main()
                cached = [
                    assignment_06.sha256_file(path) for path in products]
            self.assertEqual(fresh, cached)


class CommittedOutputContractTest(unittest.TestCase):
    def test_assignment_06_artifacts_and_public_data_contract(self):
        for relative in (
            "data/provenance/nasa_power_1991_2023.json",
            "data/processed/assignment-06/weather_daily.csv",
            "data/processed/assignment-06/weather_summary.json",
            "notebooks/06_weather_analysis.ipynb",
            "docs/assets/weather_trends.png",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        daily = pd.read_csv(
            ROOT / "data/processed/assignment-06/weather_daily.csv",
            parse_dates=["date"],
        )
        self.assertEqual(len(daily), 12053)
        self.assertFalse(daily["date"].duplicated().any())
        self.assertTrue(
            daily["date"].equals(
                pd.Series(pd.date_range(
                    "1991-01-01", "2023-12-31", freq="D"),
                    name="date",
                )
            )
        )
        self.assertTrue(
            daily["precip_mm"].dropna().ge(0).all())
        anomaly_dates = daily.loc[
            daily["t2m_anomaly_c"].notna(), "date"]
        self.assertTrue(anomaly_dates.dt.year.eq(2023).all())

        summary = json.loads(
            (ROOT / "data/processed/assignment-06/"
             "weather_summary.json").read_text())
        self.assertEqual(summary["record_count"], 12053)
        self.assertIn("t2m_anomaly_2023_c", summary)
        self.assertIn("precip_2023_mm", summary)

        provenance = json.loads(
            (ROOT / "data/provenance/"
             "nasa_power_1991_2023.json").read_text())
        for key in (
            "dataset", "source_organization", "source_name", "source_urls",
            "retrieved_utc", "source_version", "sha256", "source_crs",
            "output_crs", "producer", "counts", "license_note",
        ):
            self.assertIn(key, provenance)
        self.assertEqual(provenance["request"]["parameters"],
                         ["T2M", "PRECTOTCORR"])
        self.assertEqual(provenance["request"]["community"], "AG")
        self.assertEqual(provenance["request"]["start"], "19910101")
        self.assertEqual(provenance["request"]["end"], "20231231")
        self.assertEqual(provenance["counts"]["daily_rows"], 12053)

        notebook = json.loads(
            (ROOT / "notebooks/06_weather_analysis.ipynb").read_text())
        notebook_text = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
        )
        self.assertIn(
            "NASA POWER gridded assimilated estimates", notebook_text)
        self.assertGreater(
            (ROOT / "docs/assets/weather_trends.png").stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
