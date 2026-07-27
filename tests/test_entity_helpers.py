import importlib.util
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "entity_helpers.py"
)


def _install_homeassistant_stub():
    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity.DeviceInfo = lambda **kwargs: kwargs

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.entity", entity)


def _load_entity_helpers():
    _install_homeassistant_stub()
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.entity_helpers",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ConfigEntry:
    entry_id = "entry-123"
    data = {"station_id": "11813", "meteogram_id": "32737"}


class _Coordinator:
    config_entry = _ConfigEntry()


class TestEntityHelpers(unittest.TestCase):
    def test_forecast_device_is_split_from_station_device(self):
        helpers = _load_entity_helpers()

        station_info = helpers.station_device_info(_Coordinator())
        forecast_info = helpers.forecast_device_info(_Coordinator())

        self.assertEqual(station_info["identifiers"], {("shmu", "entry-123")})
        self.assertEqual(forecast_info["identifiers"], {("shmu", "entry-123_forecast")})
        self.assertEqual(forecast_info["via_device"], ("shmu", "entry-123"))
        self.assertEqual(forecast_info["model"], "ALADIN SK 4.5 km Forecast Cache")
        self.assertEqual(
            forecast_info["configuration_url"],
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km",
        )

    def test_ecmwf_meteogram_device_is_split_from_station_and_aladin_forecast(self):
        helpers = _load_entity_helpers()

        station_info = helpers.station_device_info(_Coordinator())
        forecast_info = helpers.forecast_device_info(_Coordinator())
        ecmwf_info = helpers.ecmwf_meteogram_device_info(_Coordinator())

        self.assertEqual(
            ecmwf_info["identifiers"],
            {("shmu", "entry-123_ecmwf_meteogram")},
        )
        self.assertNotEqual(ecmwf_info["identifiers"], station_info["identifiers"])
        self.assertNotEqual(ecmwf_info["identifiers"], forecast_info["identifiers"])
        self.assertEqual(ecmwf_info["via_device"], ("shmu", "entry-123"))
        self.assertEqual(
            ecmwf_info["name"],
            "SHMU ECMWF 10-day meteogram 11813",
        )
        self.assertEqual(ecmwf_info["model"], "ECMWF 10-day Meteogram Forecast Cache")
        self.assertEqual(
            ecmwf_info["configuration_url"],
            "https://www.shmu.sk/sk/"
            "?id=meteo_num_mgram10&nwp_mesto=32737&page=1",
        )


if __name__ == "__main__":
    unittest.main()
