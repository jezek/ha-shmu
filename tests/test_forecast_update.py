import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "forecast_update.py"
)


def _load_forecast_update():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.forecast_update",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _payload(source_run_id="run-1", temperature=17.2):
    return {
        "model_run_time": "2026-06-03T00:00:00Z",
        "source_url": "https://example.test/cache.json",
        "source_run_id": source_run_id,
        "rows": [{"valid_time": "2026-06-03T01:00:00Z", "temperature": temperature}],
    }


class TestForecastUpdate(unittest.TestCase):
    def test_update_forecast_cache_payload_writes_new_cache(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            result = forecast_update.update_forecast_cache_payload(
                cache_path,
                _payload(),
            )
            written = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(result["info"]["source_run_id"], "run-1")
        self.assertEqual(written["source_run_id"], "run-1")

    def test_update_forecast_cache_payload_skips_unchanged_run_id(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            forecast_update.update_forecast_cache_payload(cache_path, _payload())
            original_mtime = 1_780_000_000
            os.utime(cache_path, (original_mtime, original_mtime))

            result = forecast_update.update_forecast_cache_payload(
                cache_path,
                _payload(temperature=22.5),
            )
            stat = cache_path.stat()

        self.assertFalse(result["changed"])
        self.assertEqual(stat.st_mtime, original_mtime)

    def test_update_forecast_cache_payload_rejects_invalid_payload(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            with self.assertRaisesRegex(ValueError, "missing required field"):
                forecast_update.update_forecast_cache_payload(cache_path, {"rows": []})

        self.assertFalse(cache_path.exists())

    def test_update_forecast_cache_source_reads_local_helper_payload(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "source.json"
            cache_path = temp_path / "forecast-cache.json"
            source_path.write_text(json.dumps(_payload("run-2")), encoding="utf-8")

            result = forecast_update.update_forecast_cache_source(
                cache_path,
                str(source_path),
            )

        self.assertTrue(result["changed"])
        self.assertEqual(result["info"]["source_run_id"], "run-2")


if __name__ == "__main__":
    unittest.main()
