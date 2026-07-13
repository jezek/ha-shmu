import importlib.util
from pathlib import Path
import sys
import types
import unittest
from enum import Enum


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "button.py"


def _install_homeassistant_stubs():
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    button = types.ModuleType("homeassistant.components.button")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    entity = types.ModuleType("homeassistant.helpers.entity")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class ButtonEntity:
        pass

    class HomeAssistantError(Exception):
        pass

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    class EntityCategory(Enum):
        DIAGNOSTIC = "diagnostic"

    button.ButtonEntity = ButtonEntity
    exceptions.HomeAssistantError = HomeAssistantError
    entity.DeviceInfo = lambda **kwargs: kwargs
    entity.EntityCategory = EntityCategory
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.components", components)
    sys.modules.setdefault("homeassistant.components.button", button)
    sys.modules.setdefault("homeassistant.exceptions", exceptions)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.entity", entity)
    sys.modules.setdefault(
        "homeassistant.helpers.update_coordinator",
        update_coordinator,
    )


def _load_button():
    _install_homeassistant_stubs()
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location("custom_components.shmu.button", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ConfigEntry:
    entry_id = "entry-123"
    data = {"station_id": "11813"}


_DEFAULT_RESULT = object()


class _Coordinator:
    config_entry = _ConfigEntry()

    def __init__(self, forecast_result=_DEFAULT_RESULT, ecmwf_result=_DEFAULT_RESULT):
        self.forecast_calls = 0
        self.ecmwf_calls = 0
        self.listener_updates = 0
        self._forecast_result = (
            {"changed": False} if forecast_result is _DEFAULT_RESULT else forecast_result
        )
        self._ecmwf_result = {"changed": False} if ecmwf_result is _DEFAULT_RESULT else ecmwf_result

    async def _async_refresh_forecast_cache(self):
        self.forecast_calls += 1
        return self._forecast_result

    async def _async_refresh_ecmwf_epsgram_cache(self):
        self.ecmwf_calls += 1
        return self._ecmwf_result

    def async_update_listeners(self):
        self.listener_updates += 1


class TestRefreshButtons(unittest.IsolatedAsyncioTestCase):
    async def test_forecast_refresh_button_calls_coordinator(self):
        button = _load_button()
        coordinator = _Coordinator()

        entity = button.SHMUForecastRefreshButton(coordinator)
        await entity.async_press()

        self.assertEqual(
            entity._attr_unique_id,
            "shmu_entry-123_refresh_forecast_cache",
        )
        self.assertEqual(entity._attr_device_info["identifiers"], {("shmu", "entry-123_forecast")})
        self.assertEqual(entity._attr_entity_category.value, "diagnostic")
        self.assertEqual(coordinator.forecast_calls, 1)
        self.assertEqual(coordinator.listener_updates, 1)

    async def test_ecmwf_refresh_button_calls_coordinator(self):
        button = _load_button()
        coordinator = _Coordinator()

        entity = button.SHMUECMWFEPSGRAMRefreshButton(coordinator)
        await entity.async_press()

        self.assertEqual(
            entity._attr_unique_id,
            "shmu_entry-123_refresh_ecmwf_epsgram_cache",
        )
        self.assertEqual(
            entity._attr_device_info["identifiers"],
            {("shmu", "entry-123_ecmwf_epsgram")},
        )
        self.assertEqual(coordinator.ecmwf_calls, 1)
        self.assertEqual(coordinator.listener_updates, 1)

    async def test_refresh_button_raises_when_refresh_fails(self):
        button = _load_button()
        coordinator = _Coordinator(forecast_result=None)
        entity = button.SHMUForecastRefreshButton(coordinator)

        with self.assertRaises(button.HomeAssistantError):
            await entity.async_press()


if __name__ == "__main__":
    unittest.main()
