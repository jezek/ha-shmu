import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import types
import unittest


COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shmu"


def _load_module(name):
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(COMPONENT_DIR.parents[1])]
    shmu.__path__ = [str(COMPONENT_DIR)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        f"custom_components.shmu.{name}",
        COMPONENT_DIR / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestAladin(unittest.TestCase):
    def test_temperature_payload_is_forecast_cache_compatible(self):
        aladin = _load_module("aladin")
        forecast = _load_module("forecast")

        payload = aladin.temperature_payload(
            model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
            source_url="https://opendata.shmu.sk/example.grb",
            source_run_id="aladin-20260613-1200",
            values=[(0, 294.655), (1, None)],
        )
        rows = forecast.parse_helper_forecast(payload)

        self.assertEqual(payload["model_run_time"], "2026-06-13T12:00:00Z")
        self.assertEqual(payload["rows"][0]["valid_time"], "2026-06-13T12:00:00Z")
        self.assertEqual(payload["rows"][0]["temperature"], 21.505)
        self.assertIsNone(payload["rows"][1]["temperature"])
        self.assertEqual(rows[0].temperature, 21.505)
        self.assertIsNone(rows[1].temperature)

    def test_temperature_payload_rejects_naive_model_run_time(self):
        aladin = _load_module("aladin")

        with self.assertRaisesRegex(ValueError, "timezone"):
            aladin.temperature_payload(
                model_run_time=datetime(2026, 6, 13, 12),
                source_url="https://opendata.shmu.sk/example.grb",
                source_run_id="aladin-20260613-1200",
                values=[],
            )


if __name__ == "__main__":
    unittest.main()
