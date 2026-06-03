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


if __name__ == "__main__":
    unittest.main()
