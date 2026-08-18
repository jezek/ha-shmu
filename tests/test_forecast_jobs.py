import importlib.util
from datetime import datetime, timezone
from functools import partial
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


class TestForecastJobs(unittest.TestCase):
    def test_forecast_cache_update_job_uses_helper_source_when_configured(self):
        forecast_jobs = _load_module("forecast_jobs")
        forecast_update = sys.modules["custom_components.shmu.forecast_update"]

        job = forecast_jobs.forecast_cache_update_job(
            "/config/shmu/cache.json",
            source="/config/helper.json",
            now=datetime(2026, 6, 16, 6, tzinfo=timezone.utc),
            latitude=48.1,
            longitude=17.1,
            verify_ssl=False,
        )

        self.assertIsInstance(job, partial)
        self.assertIs(job.func, forecast_update.update_forecast_cache_source)
        self.assertEqual(job.args, ("/config/shmu/cache.json", "/config/helper.json"))
        self.assertEqual(job.keywords, {"force_refresh": False})

    def test_forecast_cache_update_job_uses_native_aladin_without_source(self):
        forecast_jobs = _load_module("forecast_jobs")
        forecast_update = sys.modules["custom_components.shmu.forecast_update"]
        now = datetime(2026, 6, 16, 6, tzinfo=timezone.utc)

        job = forecast_jobs.forecast_cache_update_job(
            "/config/shmu/cache.json",
            source="",
            now=now,
            latitude=48.1,
            longitude=17.1,
            verify_ssl=False,
        )

        self.assertIsInstance(job, partial)
        self.assertIs(
            job.func,
            forecast_update.update_forecast_cache_latest_aladin_temperature,
        )
        self.assertEqual(job.args, ("/config/shmu/cache.json",))
        self.assertEqual(
            job.keywords,
            {
                "now": now,
                "latitude": 48.1,
                "longitude": 17.1,
                "verify_ssl": False,
                "force_refresh": False,
            },
        )

    def test_forecast_cache_update_job_threads_manual_force_refresh(self):
        forecast_jobs = _load_module("forecast_jobs")

        job = forecast_jobs.forecast_cache_update_job(
            "/config/shmu/cache.json",
            source="",
            now=datetime(2026, 8, 3, 18, tzinfo=timezone.utc),
            latitude=48.1,
            longitude=17.1,
            verify_ssl=False,
            force_refresh=True,
        )

        self.assertTrue(job.keywords["force_refresh"])

    def test_ecmwf_meteogram_cache_update_job_uses_ecmwf_updater(self):
        forecast_jobs = _load_module("forecast_jobs")
        forecast_update = sys.modules["custom_components.shmu.forecast_update"]

        job = forecast_jobs.ecmwf_meteogram_cache_update_job(
            "/config/shmu/ecmwf-meteogram-cache-entry-123.json",
            station_id="31396",
        )

        self.assertIsInstance(job, partial)
        self.assertIs(
            job.func,
            forecast_update.update_forecast_cache_latest_ecmwf_meteogram,
        )
        self.assertEqual(
            job.args,
            ("/config/shmu/ecmwf-meteogram-cache-entry-123.json",),
        )
        self.assertEqual(
            job.keywords, {"station_id": "31396", "force_refresh": False}
        )

    def test_ecmwf_meteogram_cache_update_job_threads_manual_force_refresh(self):
        forecast_jobs = _load_module("forecast_jobs")

        job = forecast_jobs.ecmwf_meteogram_cache_update_job(
            "/config/shmu/ecmwf-meteogram-cache-entry-123.json",
            station_id="31396",
            force_refresh=True,
        )

        self.assertTrue(job.keywords["force_refresh"])


if __name__ == "__main__":
    unittest.main()
