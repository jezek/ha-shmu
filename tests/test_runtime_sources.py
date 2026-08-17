"""Tests for resolving independent subentries into runtime sources."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "runtime_sources.py"
)


def _load_module():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)
    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.runtime_sources", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Subentry:
    def __init__(self, subentry_id, subentry_type, data):
        self.subentry_id = subentry_id
        self.subentry_type = subentry_type
        self.data = data


class TestRuntimeSources(unittest.TestCase):
    def test_sources_are_independent_and_stably_sorted(self):
        module = _load_module()
        sources = module.runtime_sources(
            [
                _Subentry(
                    "z",
                    "meteogram",
                    {
                        "model": "ecmwf",
                        "area_id": "31396",
                        "area_name": "Pezinok",
                        "live_station_subentry_id": "a",
                    },
                ),
                _Subentry(
                    "a",
                    "live_station",
                    {"station_id": "11815", "station_name": "Pezinok - Grinava"},
                ),
                _Subentry("m", "meteogram", {"model": "aladin", "area_id": "32737"}),
            ]
        )

        self.assertEqual([source.subentry_id for source in sources], ["a", "m", "z"])
        self.assertEqual([source.source_id for source in sources], ["11815", "32737", "31396"])
        self.assertEqual([source.model for source in sources], [None, "aladin", "ecmwf"])
        self.assertEqual(
            [source.display_name for source in sources],
            ["Pezinok - Grinava", "32737", "Pezinok"],
        )
        self.assertEqual(
            [source.live_station_subentry_id for source in sources],
            ["", "", "a"],
        )

    def test_invalid_or_unknown_children_are_ignored(self):
        module = _load_module()
        sources = module.runtime_sources(
            [
                _Subentry("a", "live_station", {"station_id": ""}),
                _Subentry("b", "meteogram", {"model": "alaef", "area_id": "31396"}),
                _Subentry("c", "future_type", {"station_id": "11815"}),
            ]
        )

        self.assertEqual(sources, [])

    def test_migrated_child_requests_legacy_identifiers(self):
        module = _load_module()
        source = module.runtime_sources(
            [
                _Subentry(
                    "legacy",
                    "live_station",
                    {"station_id": "11815", "preserve_legacy_ids": True},
                )
            ]
        )[0]

        self.assertTrue(source.preserve_legacy_ids)

    def test_migrated_source_retains_entity_and_device_identifiers(self):
        module = _load_module()
        source = module.RuntimeSource(
            subentry_id="child",
            source_type="meteogram",
            source_id="31396",
            model="ecmwf",
            preserve_legacy_ids=True,
        )

        self.assertEqual(
            module.source_unique_id(
                "shmu", "entry-123", source, "ecmwf_meteogram_weather"
            ),
            "shmu_entry-123_ecmwf_meteogram_weather",
        )
        self.assertEqual(
            module.source_device_identifier(
                "shmu", "entry-123", source, "ecmwf_meteogram"
            ),
            ("shmu", "entry-123_ecmwf_meteogram"),
        )

    def test_new_source_uses_subentry_scoped_identifiers(self):
        module = _load_module()
        source = module.RuntimeSource(
            subentry_id="01K123",
            source_type="meteogram",
            source_id="31396",
            model="aladin",
        )

        self.assertEqual(
            module.source_unique_id("shmu", "entry-123", source, "weather"),
            "shmu_entry-123_01K123_weather",
        )
        self.assertEqual(
            module.source_device_identifier(
                "shmu", "entry-123", source, "forecast"
            ),
            ("shmu", "entry-123_01K123_forecast"),
        )


if __name__ == "__main__":
    unittest.main()
