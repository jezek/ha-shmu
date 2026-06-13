import importlib.util
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "cache_paths.py"
)


def _load_cache_paths():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.cache_paths",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Config:
    @staticmethod
    def path(*parts):
        return "/config/" + "/".join(parts)


class _Hass:
    config = _Config()


class _Entry:
    entry_id = "entry-123"
    data = {}
    options = {}


class TestCachePaths(unittest.TestCase):
    def test_forecast_cache_path_defaults_to_integration_owned_config_path(self):
        cache_paths = _load_cache_paths()

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), _Entry()),
            "/config/shmu/forecast-cache-entry-123.json",
        )

    def test_forecast_cache_path_uses_configured_override(self):
        cache_paths = _load_cache_paths()

        class Entry:
            entry_id = "entry-123"
            data = {"forecast_cache_path": "/config/custom-cache.json"}
            options = {}

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), Entry()),
            "/config/custom-cache.json",
        )

    def test_forecast_cache_path_options_override_data(self):
        cache_paths = _load_cache_paths()

        class Entry:
            entry_id = "entry-123"
            data = {"forecast_cache_path": "/config/data-cache.json"}
            options = {"forecast_cache_path": "/config/options-cache.json"}

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), Entry()),
            "/config/options-cache.json",
        )


if __name__ == "__main__":
    unittest.main()
