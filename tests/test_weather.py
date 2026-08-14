import importlib.util
from enum import IntFlag
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "weather.py"


def _load_weather():
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    weather_component = types.ModuleType("homeassistant.components.weather")
    helpers = types.ModuleType("homeassistant.helpers")
    sun = types.ModuleType("homeassistant.helpers.sun")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class WeatherEntity:
        pass

    class WeatherEntityFeature(IntFlag):
        FORECAST_HOURLY = 1
        FORECAST_DAILY = 2

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    weather_component.WeatherEntity = WeatherEntity
    weather_component.WeatherEntityFeature = WeatherEntityFeature
    sun.is_up = Mock(return_value=True)
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.weather"] = weather_component
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.sun"] = sun
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.shmu"] = shmu

    dependencies = {
        "cache_paths": {
            "ecmwf_meteogram_cache_path_for_entry": Mock(),
            "forecast_cache_path_for_entry": Mock(),
        },
        "const": {"DOMAIN": "shmu"},
        "entity_helpers": {
            "ecmwf_meteogram_device_info": Mock(return_value={}),
            "entity_unique_id": lambda coordinator, suffix: (
                f"shmu_{coordinator.config_entry.entry_id}_{suffix}"
            ),
            "forecast_device_info": Mock(return_value={}),
        },
        "forecast": {
            "ForecastCache": Mock(),
            "current_condition": Mock(return_value="partlycloudy"),
            "rows_as_daily_forecast": Mock(),
            "rows_as_hourly_forecast": Mock(),
        },
        "subentry_migration": {
            "MODEL_ALADIN": "aladin",
            "MODEL_ECMWF": "ecmwf",
        },
    }
    for name, values in dependencies.items():
        module = types.ModuleType(f"custom_components.shmu.{name}")
        for attribute, value in values.items():
            setattr(module, attribute, value)
        sys.modules[module.__name__] = module

    spec = importlib.util.spec_from_file_location("custom_components.shmu.weather", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, dependencies["forecast"]["current_condition"]


class _ConfigEntry:
    entry_id = "entry-123"


class _Coordinator:
    config_entry = _ConfigEntry()
    data = {
        "t": 21.5,
        "tlak": 1012.4,
        "vlh_rel": 67.0,
        "vie_pr_rych": 2.3,
        "vie_max_rych": 4.8,
        "vie_pr_smer": 245.0,
        "dohl": 20000.0,
        "zra_uhrn": 0.0,
    }
    ecmwf_forecast_rows = [object()]


class TestECMWFWeather(unittest.TestCase):
    def test_condition_uses_ecmwf_rows_and_observed_precipitation(self):
        weather, current_condition = _load_weather()
        entity = weather.SHMUECMWFMeteogramWeather(_Coordinator(), "/tmp/ecmwf.json")
        entity.hass = object()

        self.assertEqual(entity.condition, "partlycloudy")
        args, kwargs = current_condition.call_args
        self.assertIs(args[0], _Coordinator.ecmwf_forecast_rows)
        self.assertEqual(args[2], 0.0)
        self.assertIn("is_daytime_at", kwargs)

    def test_exposes_known_current_station_weather_fields(self):
        weather, _ = _load_weather()
        entity = weather.SHMUECMWFMeteogramWeather(_Coordinator(), "/tmp/ecmwf.json")

        self.assertEqual(entity.native_temperature, 21.5)
        self.assertEqual(entity.native_pressure, 1012.4)
        self.assertEqual(entity.humidity, 67.0)
        self.assertEqual(entity.native_wind_speed, 2.3)
        self.assertEqual(entity.native_wind_gust_speed, 4.8)
        self.assertEqual(entity.wind_bearing, 245.0)
        self.assertEqual(entity.native_visibility, 20000.0)
        self.assertEqual(entity._attr_native_visibility_unit, "m")


class TestWeatherPlatformRouting(unittest.IsolatedAsyncioTestCase):
    async def test_routes_model_weather_entities_to_subentries(self):
        weather, _ = _load_weather()

        def coordinator(model):
            return types.SimpleNamespace(
                config_entry=_ConfigEntry(),
                source=types.SimpleNamespace(model=model),
                _forecast_cache_path=Mock(return_value=f"/{model}.json"),
            )

        hass = types.SimpleNamespace(
            data={
                "shmu": {
                    "entry-123": {
                        "coordinators": {
                            "a": coordinator("aladin"),
                            "e": coordinator("ecmwf"),
                        }
                    }
                }
            }
        )
        batches = []

        await weather.async_setup_entry(
            hass,
            _ConfigEntry(),
            lambda entities, **kwargs: batches.append((entities, kwargs)),
        )

        self.assertEqual(
            [kwargs["config_subentry_id"] for _, kwargs in batches],
            ["a", "e"],
        )
        self.assertIsInstance(batches[0][0][0], weather.SHMUWeather)
        self.assertIsInstance(batches[1][0][0], weather.SHMUECMWFMeteogramWeather)


if __name__ == "__main__":
    unittest.main()
