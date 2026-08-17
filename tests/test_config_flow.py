"""Tests for SHMU config subentry lifecycle behavior."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "config_flow.py"


def _load_config_flow():
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    selector = types.ModuleType("homeassistant.helpers.selector")
    voluptuous = types.ModuleType("voluptuous")

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            return super().__init_subclass__()

    class ConfigSubentryFlow:
        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    class OptionsFlowWithReload:
        pass

    class SelectOptionDict(dict):
        def __init__(self, *, value, label):
            super().__init__(value=value, label=label)

    class SelectSelector:
        def __init__(self, config):
            self.config = config

    class SelectSelectorConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigSubentryFlow = ConfigSubentryFlow
    config_entries.OptionsFlowWithReload = OptionsFlowWithReload
    config_entries.ConfigEntry = object
    core.callback = lambda function: function
    data_entry_flow.FlowResult = dict
    aiohttp_client.async_get_clientsession = Mock()
    selector.SelectOptionDict = SelectOptionDict
    selector.SelectSelector = SelectSelector
    selector.SelectSelectorConfig = SelectSelectorConfig
    voluptuous.Schema = lambda value: value
    voluptuous.Required = lambda key, **kwargs: key
    voluptuous.Optional = lambda key, **kwargs: key

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.data_entry_flow": data_entry_flow,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.helpers.selector": selector,
        "voluptuous": voluptuous,
    }
    sys.modules.update(modules)

    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.shmu"] = shmu

    const = types.ModuleType("custom_components.shmu.const")
    const.DOMAIN = "shmu"
    catalog = types.ModuleType("custom_components.shmu.location_catalog")
    catalog.LocationOption = object
    catalog.async_fetch_location_catalog = Mock()
    sys.modules[const.__name__] = const
    sys.modules[catalog.__name__] = catalog

    spec = importlib.util.spec_from_file_location("custom_components.shmu.config_flow", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSubentryReload(unittest.TestCase):
    def tearDown(self):
        for name in list(sys.modules):
            if (
                name == "voluptuous"
                or name == "homeassistant"
                or name.startswith("homeassistant.")
                or name == "custom_components"
                or name == "custom_components.shmu"
                or name.startswith("custom_components.shmu.")
            ):
                sys.modules.pop(name, None)

    def test_successful_source_creation_schedules_parent_reload(self):
        module = _load_config_flow()
        flow = module.SHMUSubentryFlow()
        entry = types.SimpleNamespace(entry_id="parent-entry")
        flow._get_entry = Mock(return_value=entry)
        flow.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_schedule_reload=Mock())
        )

        result = flow._create_source_entry(
            title="Bratislava-letisko",
            unique_id="live_station:11816",
            data={"station_id": "11816"},
        )

        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(
            "parent-entry"
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"station_id": "11816"})

    def test_live_station_options_include_only_same_parent_live_children(self):
        module = _load_config_flow()
        flow = module.SHMUSubentryFlow()
        flow._get_entry = Mock(
            return_value=types.SimpleNamespace(
                subentries={
                    "live": types.SimpleNamespace(
                        subentry_id="live",
                        subentry_type="live_station",
                        title="Pezinok - Grinava",
                    ),
                    "forecast": types.SimpleNamespace(
                        subentry_id="forecast",
                        subentry_type="meteogram",
                        title="Pezinok — ALADIN",
                    ),
                }
            )
        )

        self.assertEqual(
            flow._live_station_options(),
            [{"value": "live", "label": "Pezinok - Grinava"}],
        )


if __name__ == "__main__":
    unittest.main()
