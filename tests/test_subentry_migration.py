"""Tests for dependency-free legacy subentry migration planning."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "subentry_migration.py"
)


def _load_module():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)
    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.subentry_migration", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSubentryMigration(unittest.TestCase):
    def test_legacy_parent_keeps_only_container_fields(self):
        module = _load_module()
        data = {
            "location_name": " Pezinok ",
            "station_id": "11815",
            "meteogram_id": "31396",
            "verify_ssl": False,
        }

        self.assertEqual(
            module.legacy_parent_data(data),
            {"location_name": "Pezinok", "verify_ssl": False},
        )

    def test_legacy_sources_become_station_and_both_forecast_models(self):
        module = _load_module()
        children = module.legacy_subentry_data(
            {"station_id": "11815", "meteogram_id": "31396"}
        )

        self.assertEqual(
            [child["unique_id"] for child in children],
            [
                "live_station:11815",
                "meteogram:aladin:31396",
                "meteogram:ecmwf:31396",
            ],
        )
        self.assertEqual(children[0]["data"]["station_id"], "11815")
        self.assertEqual(children[1]["data"]["area_id"], "31396")
        self.assertTrue(all(child["data"]["preserve_legacy_ids"] for child in children))

    def test_no_meteogram_sentinel_creates_only_station(self):
        module = _load_module()
        children = module.legacy_subentry_data(
            {"station_id": "11815", "meteogram_id": "none"}
        )

        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["subentry_type"], "live_station")


if __name__ == "__main__":
    unittest.main()
