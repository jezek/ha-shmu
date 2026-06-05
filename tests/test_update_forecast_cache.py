import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "update_forecast_cache.py"
SPEC = importlib.util.spec_from_file_location("update_forecast_cache", SCRIPT_PATH)
update_forecast_cache = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update_forecast_cache
SPEC.loader.exec_module(update_forecast_cache)


class TestUpdateForecastCache(unittest.TestCase):
    def test_main_validates_and_writes_cache_from_file_source(self):
        payload = {
            "model_run_time": "2026-06-03T00:00:00Z",
            "source_url": "https://example.test/cache.json",
            "source_run_id": "aladinsk-20260603-0000",
            "rows": [{"valid_time": "2026-06-03T01:00:00Z", "temperature": 17.2}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "helper.json"
            output = temp_path / "forecast-cache.json"
            source.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = update_forecast_cache.main([str(source), str(output)])

            written = json.loads(output.read_text(encoding="utf-8"))
            info = json.loads(stdout.getvalue())

        self.assertEqual(result, 0)
        self.assertEqual(written["source_run_id"], "aladinsk-20260603-0000")
        self.assertEqual(len(written["rows"]), 1)
        self.assertEqual(info["row_count"], 1)
        self.assertEqual(info["source_run_id"], "aladinsk-20260603-0000")

    def test_update_cache_rejects_invalid_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "bad.json"
            output = temp_path / "forecast-cache.json"
            source.write_text(json.dumps({"rows": []}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required field"):
                update_forecast_cache.update_cache(str(source), output)

        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
