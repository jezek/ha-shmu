import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "registry_migration.py"
)


def _load_registry_migration(entity_registry, device_registry):
    module_names = {
        "custom_components",
        "custom_components.shmu",
        "custom_components.shmu.const",
        "homeassistant",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_registry",
    }
    missing = object()
    previous_modules = {name: sys.modules.get(name, missing) for name in module_names}

    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.shmu"] = shmu

    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry_module = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry_module.async_get = Mock(return_value=device_registry)
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.async_get = Mock(return_value=entity_registry)
    helpers.device_registry = device_registry_module
    helpers.entity_registry = entity_registry_module
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.device_registry"] = device_registry_module
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry_module

    const = types.ModuleType("custom_components.shmu.const")
    const.DOMAIN = "shmu"
    sys.modules[const.__name__] = const

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.registry_migration",
        MODULE_PATH,
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


class TestRegistryMigration(unittest.IsolatedAsyncioTestCase):
    async def test_migrates_legacy_entity_and_device_identifiers(self):
        entity_registry = Mock()
        entity_registry.async_get_entity_id.side_effect = (
            lambda platform, domain, unique_id: (
                f"{platform}.legacy"
                if "epsgram" in unique_id
                else None
            )
        )
        device_registry = Mock()
        legacy_device = types.SimpleNamespace(id="legacy-device")
        device_registry.async_get_device.side_effect = (
            lambda *, identifiers: (
                legacy_device
                if any("epsgram" in identifier for _, identifier in identifiers)
                else None
            )
        )
        migration = _load_registry_migration(entity_registry, device_registry)

        await migration.async_migrate_legacy_ecmwf_registry(object(), "entry-123")

        self.assertEqual(entity_registry.async_update_entity.call_count, 2)
        entity_registry.async_update_entity.assert_any_call(
            "button.legacy",
            new_unique_id="shmu_entry-123_refresh_ecmwf_meteogram_cache",
        )
        entity_registry.async_update_entity.assert_any_call(
            "weather.legacy",
            new_unique_id="shmu_entry-123_ecmwf_meteogram_weather",
        )
        device_registry.async_update_device.assert_called_once_with(
            "legacy-device",
            new_identifiers={("shmu", "entry-123_ecmwf_meteogram")},
        )

    async def test_does_not_overwrite_new_registry_records(self):
        entity_registry = Mock()
        entity_registry.async_get_entity_id.side_effect = (
            lambda platform, domain, unique_id: f"{platform}.existing"
        )
        device_registry = Mock()
        device_registry.async_get_device.side_effect = (
            lambda *, identifiers: types.SimpleNamespace(id="existing-device")
        )
        migration = _load_registry_migration(entity_registry, device_registry)

        await migration.async_migrate_legacy_ecmwf_registry(object(), "entry-123")

        entity_registry.async_update_entity.assert_not_called()
        device_registry.async_update_device.assert_not_called()


if __name__ == "__main__":
    unittest.main()
