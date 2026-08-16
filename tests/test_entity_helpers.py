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
    def test_aladin_meteogram_page_url_targets_selected_area(self):
        helpers = _load_entity_helpers()

        self.assertEqual(
            helpers.aladin_meteogram_page_url("31396"),
            "https://www.shmu.sk/sk/"
            "?id=meteo_num_mgram&nwp_mesto=31396&page=1",
        )

    def test_new_children_have_independent_subentry_devices(self):
        helpers = _load_entity_helpers()
        source_type = types.SimpleNamespace

        live_coordinator = types.SimpleNamespace(
            config_entry=_ConfigEntry(),
            source=source_type(
                subentry_id="live-child",
                source_id="11815",
                preserve_legacy_ids=False,
            ),
        )
        forecast_coordinator = types.SimpleNamespace(
            config_entry=_ConfigEntry(),
            source=source_type(
                subentry_id="forecast-child",
                source_id="31396",
                preserve_legacy_ids=False,
            ),
        )

        station_info = helpers.station_device_info(live_coordinator)
        forecast_info = helpers.forecast_device_info(forecast_coordinator)

        self.assertEqual(
            station_info["identifiers"],
            {("shmu", "entry-123_live-child")},
        )
        self.assertEqual(station_info["name"], "SHMU Station 11815")
        self.assertEqual(
            forecast_info["identifiers"],
            {("shmu", "entry-123_forecast-child_forecast")},
        )
        self.assertEqual(forecast_info["name"], "SHMU Forecast 31396")
        self.assertNotIn("via_device", forecast_info)

    def test_new_live_aladin_and_ecmwf_children_use_three_devices(self):
        helpers = _load_entity_helpers()
        source_type = types.SimpleNamespace

        coordinators = [
            (
                helpers.station_device_info,
                source_type(
                    subentry_id="live", source_id="11813", preserve_legacy_ids=False
                ),
            ),
            (
                helpers.forecast_device_info,
                source_type(
                    subentry_id="aladin", source_id="31396", preserve_legacy_ids=False
                ),
            ),
            (
                helpers.ecmwf_meteogram_device_info,
                source_type(
                    subentry_id="ecmwf", source_id="31396", preserve_legacy_ids=False
                ),
            ),
        ]

        identifiers = {
            factory(types.SimpleNamespace(config_entry=_ConfigEntry(), source=source))["identifiers"]
            .pop()
            for factory, source in coordinators
        }

        self.assertEqual(
            identifiers,
            {
                ("shmu", "entry-123_live"),
                ("shmu", "entry-123_aladin_forecast"),
                ("shmu", "entry-123_ecmwf_ecmwf_meteogram"),
            },
        )

    def test_migrated_child_retains_legacy_forecast_device(self):
        helpers = _load_entity_helpers()
        coordinator = types.SimpleNamespace(
            config_entry=_ConfigEntry(),
            source=types.SimpleNamespace(
                subentry_id="migrated",
                source_id="32737",
                preserve_legacy_ids=True,
            ),
        )

        info = helpers.ecmwf_meteogram_device_info(coordinator)

        self.assertEqual(
            info["identifiers"],
            {("shmu", "entry-123_ecmwf_meteogram")},
        )
        self.assertEqual(info["via_device"], ("shmu", "entry-123"))

    def test_entity_unique_ids_preserve_migrated_and_scope_new_children(self):
        helpers = _load_entity_helpers()
        migrated = types.SimpleNamespace(
            config_entry=_ConfigEntry(),
            source=types.SimpleNamespace(
                subentry_id="migrated",
                preserve_legacy_ids=True,
            ),
        )
        new = types.SimpleNamespace(
            config_entry=_ConfigEntry(),
            source=types.SimpleNamespace(
                subentry_id="new-child",
                preserve_legacy_ids=False,
            ),
        )

        self.assertEqual(
            helpers.entity_unique_id(migrated, "weather"),
            "shmu_entry-123_weather",
        )
        self.assertEqual(
            helpers.entity_unique_id(
                migrated,
                "meteogram_url",
                legacy_unique_id="shmu_meteogram_url_entry-123",
            ),
            "shmu_meteogram_url_entry-123",
        )
        self.assertEqual(
            helpers.entity_unique_id(new, "weather"),
            "shmu_entry-123_new-child_weather",
        )

    def test_forecast_device_is_split_from_station_device(self):
        helpers = _load_entity_helpers()

        station_info = helpers.station_device_info(_Coordinator())
        forecast_info = helpers.forecast_device_info(_Coordinator())

        self.assertEqual(station_info["identifiers"], {("shmu", "entry-123")})
        self.assertEqual(
            station_info["configuration_url"],
            "https://opendata.shmu.sk/meteorology/climate/now/data/",
        )
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
            "https://www.shmu.sk/data/datanwp/json/ecmwf/",
        )


if __name__ == "__main__":
    unittest.main()
