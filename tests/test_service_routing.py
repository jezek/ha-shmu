import importlib.util
from pathlib import Path
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "service_routing.py"
)
SPEC = importlib.util.spec_from_file_location("service_routing_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
forecast_coordinator = MODULE.forecast_coordinator


def _coordinator(model):
    return types.SimpleNamespace(source=types.SimpleNamespace(model=model))


class TestServiceRouting(unittest.TestCase):
    def test_selects_only_matching_model(self):
        aladin = _coordinator("aladin")
        entry_data = {
            "coordinators": {"live": _coordinator(None), "aladin": aladin}
        }

        self.assertIs(forecast_coordinator(entry_data, "aladin"), aladin)

    def test_requires_subentry_for_multiple_same_model_sources(self):
        first = _coordinator("aladin")
        second = _coordinator("aladin")
        entry_data = {"coordinators": {"first": first, "second": second}}

        with self.assertRaisesRegex(ValueError, "Set subentry_id"):
            forecast_coordinator(entry_data, "aladin")
        self.assertIs(
            forecast_coordinator(entry_data, "aladin", "second"), second
        )

    def test_rejects_unknown_or_wrong_model_subentry(self):
        entry_data = {"coordinators": {"forecast": _coordinator("ecmwf")}}

        with self.assertRaisesRegex(ValueError, "Unknown SHMU subentry_id"):
            forecast_coordinator(entry_data, "aladin", "missing")
        with self.assertRaisesRegex(ValueError, "is not a aladin source"):
            forecast_coordinator(entry_data, "aladin", "forecast")
