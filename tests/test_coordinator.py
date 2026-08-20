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
        "custom_components.shmu.registry_migration",
        "custom_components.shmu.runtime_sources",
        "custom_components.shmu.services",
        "custom_components.shmu.subentry_migration",
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

    class ConfigSubentry:
        _next_id = 0

        def __init__(self, *, data, subentry_type, title, unique_id):
            type(self)._next_id += 1
            self.subentry_id = f"child-{type(self)._next_id}"
            self.data = data
            self.subentry_type = subentry_type
            self.title = title
            self.unique_id = unique_id

    config_entries.ConfigSubentry = ConfigSubentry
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
    homeassistant.config_entries = config_entries
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
            "forecast_cache_path_for_subentry": Mock(),
            "migrate_legacy_ecmwf_meteogram_cache": Mock(),
            "seed_subentry_cache_from_legacy": Mock(),
        },
        "const": {"CONF_FORECAST_SOURCE": "forecast_source", "DOMAIN": "shmu"},
        "api": {"SHMUAPI": type("SHMUAPI", (), {})},
        "forecast": {
            "ForecastCache": Mock(
                return_value=types.SimpleNamespace(load=Mock())
            ),
            "sparse_daily_completion_info": Mock(
                return_value=[
                    {
                        "date": "2026-08-19",
                        "missing_boundaries": ["start", "end"],
                    }
                ]
            ),
        },
        "forecast_jobs": {
            "ecmwf_meteogram_cache_update_job": Mock(),
            "forecast_cache_update_job": Mock(),
            "leading_day_aladin_fallback_job": Mock(),
        },
        "registry_migration": {
            "async_migrate_aladin_source_devices": AsyncMock(),
            "async_migrate_legacy_ecmwf_registry": AsyncMock(),
        },
        "runtime_sources": {
            "RuntimeSource": type("RuntimeSource", (), {}),
            "runtime_sources": Mock(return_value=[]),
        },
        "services": {
            "async_setup_services": AsyncMock(),
            "async_unload_services": AsyncMock(),
        },
        "subentry_migration": {
            "MODEL_ALADIN": "aladin",
            "MODEL_ECMWF": "ecmwf",
            "SUBENTRY_LIVE_STATION": "live_station",
            "legacy_parent_data": Mock(),
            "legacy_subentry_data": Mock(),
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
    async def test_module_migration_creates_children_and_updates_parent(self):
        coordinator_module = _load_coordinator_module()
        coordinator_module.legacy_subentry_data.return_value = [
            {
                "data": {"station_id": "11815"},
                "subentry_type": "live_station",
                "title": "Pezinok",
                "unique_id": "live_station:11815",
            }
        ]
        coordinator_module.legacy_parent_data.return_value = {
            "location_name": "Pezinok",
            "verify_ssl": True,
        }
        existing = types.SimpleNamespace(
            subentry_id="existing", unique_id="live_station:99999"
        )
        entry = types.SimpleNamespace(
            version=1,
            data={"station_id": "11815"},
            subentries={"existing": existing},
        )
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_add_subentry=Mock(), async_update_entry=Mock()
            )
        )

        result = await coordinator_module.async_migrate_entry(hass, entry)

        self.assertTrue(result)
        update = hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(update["version"], 2)
        self.assertEqual(update["minor_version"], 0)
        self.assertEqual(update["title"], "Pezinok")
        self.assertNotIn("subentries", update)
        hass.config_entries.async_add_subentry.assert_called_once()

    async def test_setup_entry_stores_source_mapping_and_forwards_platforms(self):
        coordinator_module = _load_coordinator_module()
        coordinators = {"station": object(), "forecast": object()}
        coordinator_module.async_create_source_coordinators = AsyncMock(
            return_value=coordinators
        )
        config_entries = types.SimpleNamespace(
            async_forward_entry_setups=AsyncMock()
        )
        hass = types.SimpleNamespace(
            data={},
            config_entries=config_entries,
            async_add_executor_job=AsyncMock(),
        )
        entry = types.SimpleNamespace(entry_id="entry", subentries={})

        result = await coordinator_module.async_setup_entry(hass, entry)

        self.assertTrue(result)
        self.assertEqual(
            hass.data["shmu"]["entry"], {"coordinators": coordinators}
        )
        coordinator_module.async_create_source_coordinators.assert_awaited_once_with(
            hass, entry
        )
        config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, ["sensor", "weather", "button"]
        )

    async def test_unload_entry_removes_source_mapping(self):
        coordinator_module = _load_coordinator_module()
        config_entries = types.SimpleNamespace(
            async_unload_platforms=AsyncMock(return_value=True)
        )
        hass = types.SimpleNamespace(
            data={"shmu": {"entry": {"coordinators": {}}}},
            config_entries=config_entries,
        )
        entry = types.SimpleNamespace(entry_id="entry")

        result = await coordinator_module.async_unload_entry(hass, entry)

        self.assertTrue(result)
        self.assertNotIn("entry", hass.data["shmu"])
        config_entries.async_unload_platforms.assert_awaited_once_with(
            entry, ["sensor", "weather", "button"]
        )

    async def test_source_coordinator_factory_refreshes_and_indexes_children(self):
        coordinator_module = _load_coordinator_module()
        live = types.SimpleNamespace(
            subentry_id="live", model=None, preserve_legacy_ids=True
        )
        ecmwf = types.SimpleNamespace(
            subentry_id="forecast", model="ecmwf", preserve_legacy_ids=True
        )
        coordinator_module.runtime_sources.return_value = [live, ecmwf]
        hass = types.SimpleNamespace(async_add_executor_job=AsyncMock())
        entry = types.SimpleNamespace(subentries={"live": live, "forecast": ecmwf})
        created = []

        def factory(_hass, _entry, source):
            coordinator = types.SimpleNamespace(
                source=source,
                async_config_entry_first_refresh=AsyncMock(),
            )
            created.append(coordinator)
            return coordinator

        result = await coordinator_module.async_create_source_coordinators(
            hass, entry, factory
        )

        self.assertEqual(result, {"live": created[0], "forecast": created[1]})
        created[0].async_config_entry_first_refresh.assert_awaited_once_with()
        created[1].async_config_entry_first_refresh.assert_awaited_once_with()
        hass.async_add_executor_job.assert_awaited_once_with(
            coordinator_module.seed_subentry_cache_from_legacy,
            hass,
            entry,
            "forecast",
            "ecmwf",
        )

    async def test_failed_live_child_does_not_block_meteogram_children(self):
        coordinator_module = _load_coordinator_module()
        live = types.SimpleNamespace(
            subentry_id="live",
            source_id="11816",
            model=None,
            preserve_legacy_ids=False,
        )
        aladin = types.SimpleNamespace(
            subentry_id="aladin",
            source_id="31396",
            model="aladin",
            preserve_legacy_ids=False,
        )
        ecmwf = types.SimpleNamespace(
            subentry_id="ecmwf",
            source_id="31396",
            model="ecmwf",
            preserve_legacy_ids=False,
        )
        coordinator_module.runtime_sources.return_value = [live, aladin, ecmwf]
        hass = types.SimpleNamespace(async_add_executor_job=AsyncMock())
        entry = types.SimpleNamespace(
            subentries={"live": live, "aladin": aladin, "ecmwf": ecmwf}
        )
        coordinators = {
            "live": types.SimpleNamespace(
                source=live,
                async_config_entry_first_refresh=AsyncMock(
                    side_effect=ValueError("No data found for station ID: 11816")
                ),
            ),
            "aladin": types.SimpleNamespace(
                source=aladin, async_config_entry_first_refresh=AsyncMock()
            ),
            "ecmwf": types.SimpleNamespace(
                source=ecmwf, async_config_entry_first_refresh=AsyncMock()
            ),
        }

        result = await coordinator_module.async_create_source_coordinators(
            hass,
            entry,
            lambda _hass, _entry, source: coordinators[source.subentry_id],
        )

        self.assertEqual(
            result,
            coordinators,
        )
        coordinators["live"].async_config_entry_first_refresh.assert_awaited_once_with()
        coordinators["aladin"].async_config_entry_first_refresh.assert_awaited_once_with()
        coordinators["ecmwf"].async_config_entry_first_refresh.assert_awaited_once_with()

    async def test_empty_parent_creates_no_source_coordinators(self):
        coordinator_module = _load_coordinator_module()
        coordinator_module.runtime_sources.return_value = []
        hass = types.SimpleNamespace(async_add_executor_job=AsyncMock())
        entry = types.SimpleNamespace(subentries={})

        result = await coordinator_module.async_create_source_coordinators(
            hass, entry, Mock()
        )

        self.assertEqual(result, {})
        hass.async_add_executor_job.assert_not_awaited()

    async def test_aladin_child_refreshes_only_its_forecast(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._hass = object()
        coordinator._api = None
        coordinator.source = types.SimpleNamespace(model="aladin")
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock()

        result = await coordinator._async_update_data()

        self.assertEqual(result, {})
        coordinator._async_refresh_forecast_cache.assert_awaited_once_with()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_not_awaited()

    async def test_ecmwf_child_refreshes_only_its_forecast(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._hass = object()
        coordinator._api = None
        coordinator.source = types.SimpleNamespace(model="ecmwf")
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock()

        result = await coordinator._async_update_data()

        self.assertEqual(result, {})
        coordinator._async_refresh_forecast_cache.assert_not_awaited()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_awaited_once_with()

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

    async def test_update_preserves_valid_station_data_during_transient_station_miss(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._hass = object()
        coordinator.data = {"t": 21.5, "minuta": "2026-08-05T22:32:00"}
        coordinator._api = types.SimpleNamespace(
            fetch_data=AsyncMock(side_effect=ValueError("station missing"))
        )
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock(return_value=None)

        result = await coordinator._async_update_data()

        self.assertIs(result, coordinator.data)
        coordinator._async_refresh_forecast_cache.assert_awaited_once_with()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_awaited_once_with()

    async def test_initial_station_miss_remains_a_failed_update(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        coordinator._hass = object()
        coordinator.data = None
        coordinator._api = types.SimpleNamespace(
            fetch_data=AsyncMock(side_effect=ValueError("station missing"))
        )
        coordinator._async_refresh_forecast_cache = AsyncMock()
        coordinator._async_refresh_ecmwf_meteogram_cache = AsyncMock(return_value=None)

        with self.assertRaises(coordinator_module.UpdateFailed):
            await coordinator._async_update_data()

        coordinator._async_refresh_forecast_cache.assert_not_awaited()
        coordinator._async_refresh_ecmwf_meteogram_cache.assert_not_awaited()

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

    async def test_ecmwf_refresh_records_and_warns_about_sparse_daily_completion(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        dt = __import__("datetime")
        base = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        rows = [
            types.SimpleNamespace(
                valid_time=base + dt.timedelta(hours=hour)
            )
            for hour in range(0, 49, 3)
        ]
        coordinator._hass = types.SimpleNamespace(
            config=types.SimpleNamespace(time_zone="Europe/Bratislava"),
            async_add_executor_job=AsyncMock(
                side_effect=[
                    {"changed": True, "info": {"row_count": len(rows)}},
                    rows,
                ]
            ),
        )
        coordinator._forecast_cache_path = Mock(return_value="/tmp/ecmwf.json")
        coordinator._default_meteogram_station_id = Mock(return_value="31396")

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING") as logs:
            result = await coordinator._async_refresh_ecmwf_meteogram_cache()

        self.assertIsNotNone(result)
        self.assertGreater(
            coordinator.ecmwf_cache_info["synthetic_daily_completion_count"], 0
        )
        self.assertTrue(coordinator.ecmwf_cache_info["synthetic_daily_completion"])
        self.assertIn("surrounding sparse samples", "\n".join(logs.output))

    async def test_history_gap_uses_native_aladin_leading_day_fallback(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        first = __import__("datetime").datetime(2026, 8, 5, 12, tzinfo=__import__("datetime").timezone.utc)
        coordinator.forecast_rows = [types.SimpleNamespace(valid_time=first)]
        coordinator.forecast_historical_temperatures = {}
        coordinator.forecast_history_info = {}
        coordinator._api = types.SimpleNamespace(
            fetch_temperature_history=AsyncMock(side_effect=ValueError("missing hour"))
        )
        coordinator._entry = types.SimpleNamespace(options={}, data={})
        coordinator._verify_ssl = True
        fallback = {
            "temperatures": {first.replace(hour=hour): 10.0 + hour for hour in range(12)},
            "info": {"source": "aladin_leading_day_fallback"},
        }
        coordinator._hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=48.289, longitude=17.267),
            async_add_executor_job=AsyncMock(return_value=fallback),
        )

        await coordinator._async_refresh_forecast_history()

        self.assertEqual(len(coordinator.forecast_historical_temperatures), 23)
        self.assertEqual(
            coordinator.forecast_history_info["source"],
            "aladin_leading_day_fallback",
        )
        self.assertEqual(coordinator.forecast_history_info["synthetic_hour_count"], 11)

    async def test_history_gap_does_not_use_aladin_fallback_for_helper_source(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        first = __import__("datetime").datetime(2026, 8, 5, 12, tzinfo=__import__("datetime").timezone.utc)
        coordinator.forecast_rows = [types.SimpleNamespace(valid_time=first)]
        coordinator.forecast_historical_temperatures = {}
        coordinator.forecast_history_info = {}
        coordinator._api = types.SimpleNamespace(
            fetch_temperature_history=AsyncMock(side_effect=ValueError("missing hour"))
        )
        coordinator._entry = types.SimpleNamespace(
            options={"forecast_source": "/tmp/helper.json"}, data={}
        )
        coordinator._verify_ssl = True
        coordinator._hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=48.289, longitude=17.267),
            async_add_executor_job=AsyncMock(),
        )

        await coordinator._async_refresh_forecast_history()

        coordinator._hass.async_add_executor_job.assert_not_awaited()
        self.assertEqual(coordinator.forecast_historical_temperatures, {})

    def test_synthetic_leading_hours_ignore_temperatures_from_other_days(self):
        coordinator_module = _load_coordinator_module()
        coordinator = object.__new__(coordinator_module.SHMUDataUpdateCoordinator)
        dt = __import__("datetime")
        first = dt.datetime(2026, 8, 5, 12, tzinfo=dt.timezone.utc)
        coordinator.forecast_rows = [
            types.SimpleNamespace(valid_time=first, temperature=18.0)
        ]
        coordinator.forecast_historical_temperatures = {
            first.replace(hour=11): 20.0,
            first - dt.timedelta(days=1): -10.0,
        }
        coordinator.forecast_history_info = {}
        coordinator._hass = types.SimpleNamespace(
            config=types.SimpleNamespace(time_zone="UTC")
        )

        coordinator._synthesize_missing_leading_forecast_hours(first)

        synthetic = [
            temperature
            for timestamp, temperature in coordinator.forecast_historical_temperatures.items()
            if timestamp.date() == first.date() and timestamp.hour not in {11, 12}
        ]
        self.assertEqual(synthetic, [18.0] * 22)


if __name__ == "__main__":
    unittest.main()
