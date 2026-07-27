import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "__init__.py"
)


def _load_coordinator_module():
    module_names = {
        "custom_components",
        "custom_components.shmu",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.event",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.aiohttp_client",
        "custom_components.shmu.cache_paths",
        "custom_components.shmu.const",
        "custom_components.shmu.api",
        "custom_components.shmu.forecast",
        "custom_components.shmu.forecast_jobs",
        "custom_components.shmu.services",
    }
    missing = object()
    previous_modules = {
        name: sys.modules.get(name, missing)
        for name in module_names
    }

    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.shmu"] = shmu

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda function: function
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_change = Mock()
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = Mock(return_value=object())

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    dependency_values = {
        "cache_paths": {
            "ecmwf_meteogram_cache_path_for_entry": Mock(),
            "forecast_cache_path_for_entry": Mock(),
            "migrate_legacy_ecmwf_meteogram_cache": Mock(),
        },
        "const": {"CONF_FORECAST_SOURCE": "forecast_source", "DOMAIN": "shmu"},
        "api": {"SHMUAPI": type("SHMUAPI", (), {})},
        "forecast": {"ForecastCache": type("ForecastCache", (), {})},
        "forecast_jobs": {
            "ecmwf_meteogram_cache_update_job": Mock(),
            "forecast_cache_update_job": Mock(),
        },
        "services": {
            "async_setup_services": AsyncMock(),
            "async_unload_services": AsyncMock(),
        },
    }
    for name, values in dependency_values.items():
        module = types.ModuleType(f"custom_components.shmu.{name}")
        for attribute, value in values.items():
            setattr(module, attribute, value)
        sys.modules[module.__name__] = module

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.coordinator_under_test",
        MODULE_PATH,
        submodule_search_locations=None,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in previous_modules.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


class TestCoordinatorForecastLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_update_refreshes_aladin_and_meteogram_before_returning_station_data(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._hass = object()
        coordinator._api = types.SimpleNamespace(
            fetch_data=AsyncMock(return_value={"station": "data"})
        )
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock(return_value=None)

        result = await coordinator._async_update_data()

        self.assertEqual(result, {"station": "data"})
        coordinator._async_refresh_forecast_cache.assert_awaited_once_with()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_awaited_once_with()

    async def test_midnight_refreshes_both_forecasts_and_notifies_entities(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock(return_value=None)
        coordinator.async_update_listeners = Mock()

        await coordinator._async_midnight_forecast_refresh()

        coordinator._async_refresh_forecast_cache.assert_awaited_once_with()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_awaited_once_with()
        coordinator.async_update_listeners.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
