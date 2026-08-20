import importlib.util
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "sensor.py"


def _load_sensor():
    sensor_component = types.ModuleType("homeassistant.components.sensor")
    const = types.ModuleType("homeassistant.const")
    entity = types.ModuleType("homeassistant.helpers.entity")
    update = types.ModuleType("homeassistant.helpers.update_coordinator")
    util_dt = types.ModuleType("homeassistant.util.dt")

    class SensorEntity:
        pass

    class SensorDeviceClass(Enum):
        HUMIDITY = "humidity"
        PRESSURE = "pressure"
        TEMPERATURE = "temperature"
        TIMESTAMP = "timestamp"
        WIND_SPEED = "wind_speed"

    class SensorStateClass(Enum):
        MEASUREMENT = "measurement"

    class EntityCategory(Enum):
        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    sensor_component.SensorEntity = SensorEntity
    sensor_component.SensorDeviceClass = SensorDeviceClass
    sensor_component.SensorStateClass = SensorStateClass
    const.PERCENTAGE = "%"
    entity.EntityCategory = EntityCategory
    update.CoordinatorEntity = CoordinatorEntity
    util_dt.now = Mock(return_value=datetime(2026, 8, 20, 10, 2, tzinfo=timezone.utc))

    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.sensor": sensor_component,
        "homeassistant.const": const,
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity": entity,
        "homeassistant.helpers.update_coordinator": update,
        "homeassistant.util": types.ModuleType("homeassistant.util"),
        "homeassistant.util.dt": util_dt,
    }
    sys.modules.update(modules)

    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.shmu"] = shmu

    forecast_summary = Mock(return_value={"tomorrow_min_temperature": 7.5})
    dependencies = {
        "cache_paths": {"forecast_cache_path_for_entry": Mock()},
        "const": {"DEFAULT_STATION_ID": "11813", "DOMAIN": "shmu"},
        "entity_helpers": {
            "aladin_meteogram_page_url": Mock(),
            "ecmwf_meteogram_device_info": Mock(return_value={"model": "ecmwf"}),
            "entity_unique_id": lambda coordinator, suffix, **kwargs: suffix,
            "forecast_device_info": Mock(return_value={"model": "aladin"}),
            "station_device_info": Mock(return_value={}),
        },
        "forecast": {"forecast_summary": forecast_summary},
        "subentry_migration": {
            "MODEL_ALADIN": "aladin",
            "MODEL_ECMWF": "ecmwf",
            "SUBENTRY_LIVE_STATION": "live_station",
        },
    }
    for name, values in dependencies.items():
        module = types.ModuleType(f"custom_components.shmu.{name}")
        for attribute, value in values.items():
            setattr(module, attribute, value)
        sys.modules[module.__name__] = module

    spec = importlib.util.spec_from_file_location("custom_components.shmu.sensor", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, forecast_summary


class TestECMWFSensorParity(unittest.TestCase):
    def test_ecmwf_receives_forecast_summaries_from_ecmwf_rows(self):
        sensor, forecast_summary = _load_sensor()
        ecmwf_rows = [object()]
        coordinator = types.SimpleNamespace(
            config_entry=types.SimpleNamespace(entry_id="entry", data={}),
            source=types.SimpleNamespace(
                model="ecmwf", source_id="31396", source_type="forecast"
            ),
            data={},
            forecast_rows=["aladin-row"],
            ecmwf_forecast_rows=ecmwf_rows,
            ecmwf_cache_info={"downloaded_time": "2026-08-20T09:00:00Z"},
            _forecast_cache_path=Mock(return_value="/ecmwf.json"),
        )

        entities = sensor._build_sensors(object(), coordinator)
        summaries = [
            entity
            for entity in entities
            if isinstance(entity, sensor.SHMUForecastSummarySensor)
        ]

        self.assertEqual(len(summaries), 7)
        self.assertEqual(summaries[0].native_value, 7.5)
        self.assertIs(forecast_summary.call_args.args[0], ecmwf_rows)
        self.assertEqual(summaries[0]._attr_device_info["model"], "ecmwf")
        coordinator._forecast_cache_path.assert_called_once_with("ecmwf")

        diagnostics = [
            entity
            for entity in entities
            if isinstance(entity, sensor.SHMUECMWFMeteogramCacheInfoSensor)
        ]
        age = next(entity for entity in diagnostics if entity._info_key == "age_seconds")
        self.assertEqual(len(diagnostics), 8)
        self.assertEqual(age.native_value, 3720)


if __name__ == "__main__":
    unittest.main()
