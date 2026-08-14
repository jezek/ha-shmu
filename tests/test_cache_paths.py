import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "shmu" / "cache_paths.py"
)


def _load_cache_paths():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.cache_paths",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Config:
    @staticmethod
    def path(*parts):
        return "/config/" + "/".join(parts)


class _Hass:
    config = _Config()


class _Entry:
    entry_id = "entry-123"
    data = {}
    options = {}


class TestCachePaths(unittest.TestCase):
    def test_forecast_cache_path_defaults_to_integration_owned_config_path(self):
        cache_paths = _load_cache_paths()

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), _Entry()),
            "/config/shmu/forecast-cache-entry-123.json",
        )

    def test_forecast_cache_path_uses_configured_override(self):
        cache_paths = _load_cache_paths()

        class Entry:
            entry_id = "entry-123"
            data = {"forecast_cache_path": "/config/custom-cache.json"}
            options = {}

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), Entry()),
            "/config/custom-cache.json",
        )

    def test_forecast_cache_path_options_override_data(self):
        cache_paths = _load_cache_paths()

        class Entry:
            entry_id = "entry-123"
            data = {"forecast_cache_path": "/config/data-cache.json"}
            options = {"forecast_cache_path": "/config/options-cache.json"}

        self.assertEqual(
            cache_paths.forecast_cache_path_for_entry(_Hass(), Entry()),
            "/config/options-cache.json",
        )

    def test_ecmwf_meteogram_cache_path_defaults_to_separate_integration_owned_path(self):
        cache_paths = _load_cache_paths()

        self.assertEqual(
            cache_paths.ecmwf_meteogram_cache_path_for_entry(_Hass(), _Entry()),
            "/config/shmu/ecmwf-meteogram-cache-entry-123.json",
        )
        self.assertNotEqual(
            cache_paths.ecmwf_meteogram_cache_path_for_entry(_Hass(), _Entry()),
            cache_paths.forecast_cache_path_for_entry(_Hass(), _Entry()),
        )

    def test_subentry_cache_paths_are_model_and_child_specific(self):
        cache_paths = _load_cache_paths()

        aladin = cache_paths.forecast_cache_path_for_subentry(
            _Hass(), _Entry(), "child-a", "aladin"
        )
        ecmwf = cache_paths.forecast_cache_path_for_subentry(
            _Hass(), _Entry(), "child-b", "ecmwf"
        )

        self.assertEqual(
            aladin,
            "/config/shmu/aladin-cache-entry-123-child-a.json",
        )
        self.assertEqual(
            ecmwf,
            "/config/shmu/ecmwf-cache-entry-123-child-b.json",
        )

    def test_subentry_cache_rejects_unknown_model(self):
        cache_paths = _load_cache_paths()

        with self.assertRaises(ValueError):
            cache_paths.forecast_cache_path_for_subentry(
                _Hass(), _Entry(), "child", "alaef"
            )

    def test_seeds_migrated_child_cache_without_removing_legacy(self):
        cache_paths = _load_cache_paths()

        with tempfile.TemporaryDirectory() as config_dir:
            class Config:
                @staticmethod
                def path(*parts):
                    return str(Path(config_dir, *parts))

            class Hass:
                config = Config()

            legacy = Path(config_dir, "shmu", "forecast-cache-entry-123.json")
            legacy.parent.mkdir()
            legacy.write_text("legacy-aladin", encoding="utf-8")

            self.assertTrue(
                cache_paths.seed_subentry_cache_from_legacy(
                    Hass(), _Entry(), "child-a", "aladin"
                )
            )
            child = Path(
                config_dir,
                "shmu",
                "aladin-cache-entry-123-child-a.json",
            )
            self.assertEqual(child.read_text(encoding="utf-8"), "legacy-aladin")
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-aladin")

            child.write_text("newer", encoding="utf-8")
            self.assertFalse(
                cache_paths.seed_subentry_cache_from_legacy(
                    Hass(), _Entry(), "child-a", "aladin"
                )
            )
            self.assertEqual(child.read_text(encoding="utf-8"), "newer")

    def test_migrates_legacy_ecmwf_epsgram_cache(self):
        cache_paths = _load_cache_paths()

        with tempfile.TemporaryDirectory() as config_dir:
            class Config:
                @staticmethod
                def path(*parts):
                    return str(Path(config_dir, *parts))

            class Hass:
                config = Config()

            legacy_path = Path(
                config_dir,
                "shmu",
                "ecmwf-epsgram-cache-entry-123.json",
            )
            legacy_path.parent.mkdir()
            legacy_path.write_text('{"forecast": []}', encoding="utf-8")

            self.assertTrue(
                cache_paths.migrate_legacy_ecmwf_meteogram_cache(Hass(), _Entry())
            )
            migrated_path = Path(
                config_dir,
                "shmu",
                "ecmwf-meteogram-cache-entry-123.json",
            )
            self.assertEqual(
                migrated_path.read_text(encoding="utf-8"),
                '{"forecast": []}',
            )
            self.assertFalse(legacy_path.exists())

    def test_does_not_overwrite_existing_ecmwf_meteogram_cache(self):
        cache_paths = _load_cache_paths()

        with tempfile.TemporaryDirectory() as config_dir:
            class Config:
                @staticmethod
                def path(*parts):
                    return str(Path(config_dir, *parts))

            class Hass:
                config = Config()

            cache_dir = Path(config_dir, "shmu")
            cache_dir.mkdir()
            legacy_path = cache_dir / "ecmwf-epsgram-cache-entry-123.json"
            migrated_path = cache_dir / "ecmwf-meteogram-cache-entry-123.json"
            legacy_path.write_text("legacy", encoding="utf-8")
            migrated_path.write_text("current", encoding="utf-8")

            self.assertFalse(
                cache_paths.migrate_legacy_ecmwf_meteogram_cache(Hass(), _Entry())
            )
            self.assertEqual(migrated_path.read_text(encoding="utf-8"), "current")
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), "legacy")


if __name__ == "__main__":
    unittest.main()
