import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest


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

        hourly = forecast.rows_as_hourly_forecast(rows)

        self.assertEqual(hourly[0]["datetime"], "2026-06-03T01:00:00Z")
        self.assertEqual(hourly[0]["condition"], "rainy")
        self.assertEqual(hourly[0]["temperature"], 17.0)
        self.assertEqual(hourly[0]["pressure"], 1010.0)
        self.assertEqual(hourly[0]["wind_bearing"], 180.0)
        self.assertEqual(hourly[0]["wind_gust_speed"], 5.0)
        self.assertEqual(hourly[0]["precipitation"], 0.3)
        self.assertEqual(hourly[1]["condition"], "cloudy")

    def test_rows_as_daily_forecast_aggregates_weather_fields(self):
        rows = forecast.parse_helper_forecast(
            {
                "model_run_time": "2026-06-03T00:00:00Z",
                "source_url": "https://example.test/aladin.json",
                "source_run_id": "run",
                "rows": [
                    {
                        "valid_time": "2026-06-03T01:00:00Z",
                        "temperature": 12,
                        "wind_speed": 2,
                        "wind_gust": 4,
                        "cloud_cover": 10,
                        "precipitation_amount": 0,
                    },
                    {
                        "valid_time": "2026-06-03T15:00:00Z",
                        "temperature": 21,
                        "wind_speed": 6,
                        "wind_gust": 9,
                        "cloud_cover": 80,
                        "precipitation_amount": 1.5,
                    },
                ],
            }
        )

        daily = forecast.rows_as_daily_forecast(rows)

        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["datetime"], "2026-06-03")
        self.assertEqual(daily[0]["condition"], "rainy")
        self.assertEqual(daily[0]["temperature"], 21.0)
        self.assertEqual(daily[0]["templow"], 12.0)
        self.assertEqual(daily[0]["precipitation"], 1.5)
        self.assertEqual(daily[0]["wind_speed"], 6.0)
        self.assertEqual(daily[0]["wind_gust_speed"], 9.0)
        self.assertEqual(daily[0]["cloud_coverage"], 45.0)

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


if __name__ == "__main__":
    unittest.main()
