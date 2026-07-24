import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "forecast.py"
SPEC = importlib.util.spec_from_file_location("shmu_forecast", MODULE_PATH)
forecast = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = forecast
SPEC.loader.exec_module(forecast)


class TestForecastHelperContract(unittest.TestCase):
    def test_parse_helper_forecast_normalizes_rows(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "aladinsk-20260603-0000",
                "rows": [
                    {
                        "valid_time": "2026-06-03T03:00:00+00:00",
                        "temperature": "18.5",
                        "pressure": 1012,
                        "wind_speed": 4.2,
                        "wind_direction": 270,
                        "wind_gust": 7.5,
                        "cloud_cover": 40,
                        "precipitation_amount": 0.2,
                    }
                ],
            }
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.model_run_time, datetime(2026, 6, 3, tzinfo=timezone.utc))
        self.assertEqual(row.valid_time, datetime(2026, 6, 3, 3, tzinfo=timezone.utc))
        self.assertEqual(row.lead_hours, 3.0)
        self.assertEqual(row.temperature, 18.5)
        self.assertEqual(row.pressure, 1012.0)
        self.assertEqual(row.wind_direction, 270.0)
        self.assertEqual(row.source_run_id, "aladinsk-20260603-0000")
        self.assertEqual(row.as_dict()["valid_time"], "2026-06-03T03:00:00Z")

    def test_parse_helper_forecast_rejects_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "missing required field: model_run_time"):
            forecast.parse_helper_forecast({"rows": []})

    def test_parse_helper_forecast_rejects_negative_lead_hours(self):
        with self.assertRaisesRegex(ValueError, "lead_hours must be non-negative"):
            forecast.parse_helper_forecast(
                {
                    "model_run_time": "2026-06-03T00:00:00Z",
                    "source_url": "https://example.test/aladin.json",
                    "source_run_id": "run",
                    "rows": [{"valid_time": "2026-06-03T01:00:00Z", "lead_hours": -1}],
                }
            )

    def test_forecast_cache_round_trips_helper_payload(self):
        payload = {
            "model_run_time": "2026-06-03T00:00:00Z",
            "source_url": "https://example.test/cache.json",
            "source_run_id": "aladinsk-20260603-0000",
            "rows": [
                {
                    "valid_time": "2026-06-03T01:00:00Z",
                    "temperature": 17.2,
                    "pressure": 1011.5,
                },
                {
                    "valid_time": "2026-06-03T02:00:00Z",
                    "temperature": 16.9,
                    "precipitation_amount": 0.0,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = forecast.ForecastCache(Path(temp_dir) / "point-48.15-17.11.json")
            cache.save_payload(payload)
            rows = cache.load()

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].valid_time, datetime(2026, 6, 3, 1, tzinfo=timezone.utc))
            self.assertEqual(rows[0].temperature, 17.2)
            self.assertEqual(rows[1].precipitation_amount, 0.0)

            second_cache = forecast.ForecastCache(Path(temp_dir) / "roundtrip.json")
            second_cache.save(rows)
            round_tripped = second_cache.load()

            self.assertEqual([row.as_dict() for row in round_tripped], [row.as_dict() for row in rows])

    def test_forecast_cache_rejects_empty_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = forecast.ForecastCache(Path(temp_dir) / "empty.json")
            with self.assertRaisesRegex(ValueError, "cannot save an empty forecast cache"):
                cache.save([])

    def test_forecast_cache_info_reports_freshness_metadata(self):
        payload = {
            "model_run_time": "2026-06-03T00:00:00Z",
            "source_url": "https://example.test/cache.json",
            "source_run_id": "aladinsk-20260603-0000",
            "rows": [
                {"valid_time": "2026-06-03T01:00:00Z", "temperature": 17.2},
                {"valid_time": "2026-06-03T03:00:00Z", "temperature": 18.4},
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "freshness.json"
            cache = forecast.ForecastCache(cache_path)
            cache.save_payload(payload)
            modified = datetime(2026, 6, 3, 4, tzinfo=timezone.utc)
            os.utime(cache_path, (modified.timestamp(), modified.timestamp()))

            info = cache.info(datetime(2026, 6, 3, 5, 30, tzinfo=timezone.utc))

        self.assertEqual(info["path"], str(cache_path))
        self.assertEqual(info["row_count"], 2)
        self.assertEqual(info["file_modified_time"], "2026-06-03T04:00:00Z")
        self.assertEqual(info["age_seconds"], 5400.0)
        self.assertEqual(info["model_run_time"], "2026-06-03T00:00:00Z")
        self.assertEqual(info["oldest_valid_time"], "2026-06-03T01:00:00Z")
        self.assertEqual(info["newest_valid_time"], "2026-06-03T03:00:00Z")
        self.assertEqual(info["source_run_id"], "aladinsk-20260603-0000")

    def test_rows_as_hourly_forecast_sorts_and_maps_weather_fields(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": "2026-06-03T02:00:00Z",
                        "temperature": 16,
                        "cloud_cover": 85,
                    },
                    {
                        "valid_time": "2026-06-03T01:00:00Z",
                        "temperature": 17,
                        "pressure": 1010,
                        "wind_speed": 3,
                        "wind_direction": 180,
                        "wind_gust": 5,
                        "cloud_cover": 10,
                        "precipitation_amount": 0.3,
                    },
                ],
            }
        )

        hourly = forecast.rows_as_hourly_forecast(
            rows,
            datetime(2026, 6, 3, 0, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(hourly[0]["datetime"], "2026-06-03T01:00:00Z")
        self.assertEqual(hourly[0]["condition"], "rainy")
        self.assertEqual(hourly[0]["temperature"], 17.0)
        self.assertEqual(hourly[0]["pressure"], 1010.0)
        self.assertEqual(hourly[0]["wind_bearing"], 180.0)
        self.assertEqual(hourly[0]["wind_gust_speed"], 5.0)
        self.assertEqual(hourly[0]["precipitation"], 0.3)
        self.assertEqual(hourly[1]["condition"], "cloudy")

    def test_rows_as_hourly_forecast_starts_at_upcoming_full_hour(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-19T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": f"2026-07-19T{hour:02d}:00:00Z",
                        "temperature": 10 + hour,
                    }
                    for hour in range(12, 22)
                ],
            }
        )

        hourly = forecast.rows_as_hourly_forecast(
            rows,
            datetime(2026, 7, 19, 16, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(hourly[0]["datetime"], "2026-07-19T17:00:00Z")
        self.assertEqual(len(hourly), 5)

    def test_rows_as_hourly_forecast_keeps_exact_full_hour(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-19T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {"valid_time": "2026-07-19T17:00:00Z", "temperature": 20},
                    {"valid_time": "2026-07-19T18:00:00Z", "temperature": 21},
                ],
            }
        )

        hourly = forecast.rows_as_hourly_forecast(
            rows,
            datetime(2026, 7, 19, 17, tzinfo=timezone.utc),
        )

        self.assertEqual(hourly[0]["datetime"], "2026-07-19T17:00:00Z")

    def test_rows_as_hourly_forecast_adds_daylight_flag(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-19T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": f"2026-07-19T{hour:02d}:00:00Z",
                        "cloud_cover": cloud_cover,
                    }
                    for hour, cloud_cover in ((21, 10), (22, 50))
                ],
            }
        )

        hourly = forecast.rows_as_hourly_forecast(
            rows,
            datetime(2026, 7, 19, 20, tzinfo=timezone.utc),
            is_daytime_at=lambda valid_time: False,
        )

        self.assertEqual([item["is_daytime"] for item in hourly], [False, False])
        self.assertEqual(
            [item["condition"] for item in hourly],
            ["clear-night", "clear-night"],
        )

    def test_rows_as_hourly_forecast_passes_utc_times_across_dst_boundary(self):
        bratislava = ZoneInfo("Europe/Bratislava")
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-10-24T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {"valid_time": "2026-10-25T00:00:00Z", "cloud_cover": 10},
                    {"valid_time": "2026-10-25T01:00:00Z", "cloud_cover": 10},
                ],
            }
        )
        observed: list[tuple[datetime, int, int]] = []

        def classify_daylight(valid_time: datetime) -> bool:
            local_time = valid_time.astimezone(bratislava)
            observed.append((valid_time, local_time.hour, local_time.fold))
            return False

        hourly = forecast.rows_as_hourly_forecast(
            rows,
            datetime(2026, 10, 24, 23, tzinfo=timezone.utc),
            is_daytime_at=classify_daylight,
        )

        self.assertEqual([item["is_daytime"] for item in hourly], [False, False])
        self.assertEqual(
            [item["condition"] for item in hourly],
            ["clear-night", "clear-night"],
        )
        self.assertEqual(
            observed,
            [
                (datetime(2026, 10, 25, 0, tzinfo=timezone.utc), 2, 0),
                (datetime(2026, 10, 25, 1, tzinfo=timezone.utc), 2, 1),
            ],
        )

    def test_rows_as_daily_forecast_aggregates_weather_fields(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (
                            datetime(2026, 6, 3, tzinfo=timezone.utc)
                            + timedelta(hours=hour)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "temperature": 12 if hour == 1 else 21 if hour == 15 else 16,
                        "wind_speed": 2 if hour == 1 else 6 if hour == 15 else 3,
                        "wind_gust": 4 if hour == 1 else 9 if hour == 15 else 5,
                        "cloud_cover": 10 if hour == 1 else 80 if hour == 15 else 45,
                        "precipitation_amount": 1.5 if hour == 15 else 0,
                    }
                    for hour in range(24)
                ],
            }
        )

        daily = forecast.rows_as_daily_forecast(rows)

        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["datetime"], "2026-06-03T12:00:00Z")
        self.assertEqual(daily[0]["condition"], "rainy")
        self.assertEqual(daily[0]["temperature"], 21.0)
        self.assertEqual(daily[0]["templow"], 12.0)
        self.assertEqual(daily[0]["precipitation"], 1.5)
        self.assertEqual(daily[0]["wind_speed"], 6.0)
        self.assertEqual(daily[0]["wind_gust_speed"], 9.0)
        self.assertEqual(daily[0]["cloud_coverage"], 45.0)

    def test_rows_as_daily_forecast_skips_incomplete_boundary_days(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T18:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (
                            datetime(2026, 6, 3, 18, tzinfo=timezone.utc)
                            + timedelta(hours=hour)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "temperature": 16 + hour,
                        "cloud_cover": 40,
                    }
                    for hour in range(30)
                ],
            }
        )

        daily = forecast.rows_as_daily_forecast(rows)

        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["datetime"], "2026-06-04T12:00:00Z")
        self.assertEqual(daily[0]["temperature"], 45.0)
        self.assertEqual(daily[0]["templow"], 22.0)

    def test_rows_as_daily_forecast_completes_current_day_with_history(self):
        day = datetime(2026, 7, 19, tzinfo=timezone.utc)
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-19T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (day + timedelta(hours=hour)).isoformat(),
                        "temperature": 20 + hour,
                        "precipitation_amount": 1 if hour == 15 else 0,
                    }
                    for hour in range(12, 24)
                ],
            }
        )
        history = {day + timedelta(hours=hour): 5 + hour for hour in range(12)}

        daily = forecast.rows_as_daily_forecast(rows, history, day + timedelta(hours=18))

        self.assertEqual(daily[0]["datetime"], "2026-07-19T12:00:00Z")
        self.assertEqual(daily[0]["templow"], 5.0)
        self.assertEqual(daily[0]["temperature"], 43.0)
        self.assertEqual(daily[0]["precipitation"], 1.0)

    def test_rows_as_daily_forecast_rejects_current_day_with_history_gap(self):
        day = datetime(2026, 7, 19, tzinfo=timezone.utc)
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-19T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (day + timedelta(hours=hour)).isoformat(),
                        "temperature": 20 + hour,
                    }
                    for hour in range(12, 24)
                ],
            }
        )
        history = {day + timedelta(hours=hour): 5 + hour for hour in range(11)}

        daily = forecast.rows_as_daily_forecast(rows, history, day + timedelta(hours=18))

        self.assertEqual(daily, [])

    def test_rows_as_daily_forecast_excludes_incomplete_trailing_half_day(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-07-18T12:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (
                            datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
                            + timedelta(hours=hour)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "temperature": 10 + hour,
                        "cloud_cover": 40,
                    }
                    for hour in range(73)
                ],
            }
        )

        daily = forecast.rows_as_daily_forecast(rows)

        self.assertEqual(
            [item["datetime"] for item in daily],
            [
                "2026-07-19T12:00:00Z",
                "2026-07-20T12:00:00Z",
            ],
        )
        self.assertEqual(daily[-1]["templow"], 46.0)
        self.assertEqual(daily[-1]["temperature"], 69.0)

    def test_rows_as_daily_forecast_ignores_trace_precipitation_for_condition(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": (
                            datetime(2026, 6, 3, tzinfo=timezone.utc)
                            + timedelta(hours=hour)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "temperature": 16,
                        "cloud_cover": 15,
                        "precipitation_amount": 0.01,
                    }
                    for hour in range(24)
                ],
            }
        )

        daily = forecast.rows_as_daily_forecast(rows)

        self.assertEqual(daily[0]["condition"], "sunny")
        self.assertEqual(daily[0]["precipitation"], 0.24)

    def test_forecast_summary_answers_practical_questions(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": "2026-06-03T21:00:00Z",
                        "temperature": 15,
                        "wind_gust": 4,
                        "cloud_cover": 90,
                        "precipitation_amount": 0,
                    },
                    {
                        "valid_time": "2026-06-04T03:00:00Z",
                        "temperature": 11,
                        "wind_gust": 8,
                        "cloud_cover": 20,
                        "precipitation_amount": 0,
                    },
                    {
                        "valid_time": "2026-06-04T12:00:00Z",
                        "temperature": 23,
                        "wind_gust": 12,
                        "cloud_cover": 80,
                        "precipitation_amount": 1.4,
                    },
                    {
                        "valid_time": "2026-06-05T00:00:00Z",
                        "temperature": 17,
                        "wind_gust": 6,
                        "cloud_cover": 10,
                        "precipitation_amount": 0,
                    },
                ],
            }
        )

        summary = forecast.forecast_summary(
            rows,
            datetime(2026, 6, 3, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(summary["tomorrow_min_temperature"], 11.0)
        self.assertEqual(summary["tomorrow_max_temperature"], 23.0)
        self.assertEqual(summary["next_precipitation_time"], datetime(2026, 6, 4, 12, tzinfo=timezone.utc))
        self.assertEqual(summary["next_precipitation_amount"], 1.4)
        self.assertEqual(summary["strongest_gust_time"], datetime(2026, 6, 4, 12, tzinfo=timezone.utc))
        self.assertEqual(summary["strongest_gust_speed"], 12.0)
        self.assertEqual(summary["next_clear_window_time"], datetime(2026, 6, 4, 3, tzinfo=timezone.utc))

    def test_forecast_summary_returns_none_when_no_match_exists(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [{"valid_time": "2026-06-03T01:00:00Z", "temperature": 10}],
            }
        )

        summary = forecast.forecast_summary(
            rows,
            datetime(2026, 6, 3, 20, tzinfo=timezone.utc),
        )

        self.assertIsNone(summary["tomorrow_min_temperature"])
        self.assertIsNone(summary["next_precipitation_time"])
        self.assertIsNone(summary["strongest_gust_speed"])
        self.assertIsNone(summary["next_clear_window_time"])

    def test_forecast_series_filters_field_and_window(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {"valid_time": "2026-06-03T01:00:00Z", "temperature": 17},
                    {"valid_time": "2026-06-03T02:00:00Z"},
                    {"valid_time": "2026-06-03T03:00:00Z", "temperature": 19},
                ],
            }
        )

        series = forecast.forecast_series(
            rows,
            "temperature",
            start=datetime(2026, 6, 3, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(
            series,
            [
                {
                    "valid_time": "2026-06-03T03:00:00Z",
                    "value": 19.0,
                    "lead_hours": 3.0,
                    "model_run_time": "2026-06-03T00:00:00Z",
                    "source_run_id": "run",
                }
            ],
        )

    def test_forecast_series_rejects_unknown_field(self):
        with self.assertRaisesRegex(ValueError, "unsupported forecast field"):
            forecast.forecast_series([], "humidity")

    def test_forecast_comparison_matches_nearest_observation(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {"valid_time": "2026-06-03T01:00:00Z", "temperature": 17},
                    {"valid_time": "2026-06-03T02:00:00Z", "temperature": 20},
                ],
            }
        )

        comparison = forecast.forecast_comparison(
            rows,
            [
                {"time": "2026-06-03T01:20:00Z", "value": "16.5"},
                {"time": "2026-06-03T03:00:00Z", "value": 21},
                {"time": "2026-06-03T02:00:00Z", "value": None},
            ],
            "temperature",
        )

        self.assertEqual(len(comparison), 1)
        self.assertEqual(comparison[0]["observation_time"], "2026-06-03T01:20:00Z")
        self.assertEqual(comparison[0]["forecast_valid_time"], "2026-06-03T01:00:00Z")
        self.assertEqual(comparison[0]["observed_value"], 16.5)
        self.assertEqual(comparison[0]["forecast_value"], 17.0)
        self.assertEqual(comparison[0]["error"], 0.5)
        self.assertEqual(comparison[0]["abs_error"], 0.5)
        self.assertEqual(comparison[0]["distance_minutes"], 20.0)

    def test_forecast_comparison_rounds_floating_point_noise(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {"valid_time": "2026-06-03T01:00:00Z", "temperature": 15},
                ],
            }
        )

        comparison = forecast.forecast_comparison(
            rows,
            [{"time": "2026-06-03T01:00:00Z", "value": 14.8}],
            "temperature",
        )

        self.assertEqual(comparison[0]["error"], 0.2)
        self.assertEqual(comparison[0]["abs_error"], 0.2)

    def test_forecast_comparison_rejects_bad_inputs(self):
        with self.assertRaisesRegex(ValueError, "max_distance_minutes must be non-negative"):
            forecast.forecast_comparison([], [], "temperature", max_distance_minutes=-1)
        with self.assertRaisesRegex(ValueError, "missing time"):
            forecast.forecast_comparison([], [{"value": 1}], "temperature")


if __name__ == "__main__":
    unittest.main()
