import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import struct
import sys
import types
import unittest


COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shmu"


def _load_module(name):
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(COMPONENT_DIR.parents[1])]
    shmu.__path__ = [str(COMPONENT_DIR)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        f"custom_components.shmu.{name}",
        COMPONENT_DIR / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _section(number, payload):
    return (len(payload) + 5).to_bytes(4, "big") + bytes([number]) + payload


def _message(sections, discipline=0):
    body = b"".join(sections) + b"7777"
    length = len(body) + 16
    return b"GRIB" + b"\0\0" + bytes([discipline, 2]) + length.to_bytes(8, "big") + body


def _product_section(category, number, surface_type, surface_value, forecast_time):
    return _section(
        4,
        b"".join(
            [
                (0).to_bytes(2, "big"),
                (0).to_bytes(2, "big"),
                bytes([category, number, 255, 0, 0]),
                (0).to_bytes(2, "big"),
                bytes([0, 1]),
                forecast_time.to_bytes(4, "big"),
                bytes([surface_type, 0]),
                surface_value.to_bytes(4, "big"),
                bytes([255, 255]),
                (0xFFFFFFFF).to_bytes(4, "big"),
            ]
        ),
    )


def _real_template_33_grid_section():
    return bytes.fromhex(
        "00 00 00 61 03 00 00 00 "
        "11 a0 00 00 00 21 06 ff "
        "ff ff ff ff ff ff ff ff "
        "ff ff ff ff ff ff 00 00 "
        "00 5e 00 00 00 30 02 d8 "
        "7b 36 01 01 1a c7 08 02 "
        "c1 a3 5d 01 03 66 40 00 "
        "44 aa 20 00 44 aa 20 00 "
        "40 02 c1 a3 5d 02 c1 a3 "
        "5d 00 00 00 00 00 00 00 "
        "00 00 00 00 5e 00 00 00 "
        "00 00 00 00 30 00 00 00 "
        "00"
    )


def _constant_grid_sections(points=4512, value=280.0):
    section5 = _section(
        5,
        b"".join(
            [
                points.to_bytes(4, "big"),
                (0).to_bytes(2, "big"),
                struct.pack(">f", value),
                (0).to_bytes(2, "big"),
                (0).to_bytes(2, "big"),
                bytes([0, 0]),
            ]
        ),
    )
    section6 = _section(6, bytes([255]))
    section7 = _section(7, b"")
    return section5, section6, section7


def _temperature_message(lead_hours, value):
    return _message(
        [
            _real_template_33_grid_section(),
            _product_section(0, 0, 103, 2, lead_hours),
            *_constant_grid_sections(value=value),
        ]
    )


class TestAladin(unittest.TestCase):
    def test_temperature_payload_is_forecast_cache_compatible(self):
        aladin = _load_module("aladin")
        forecast = _load_module("forecast")

        payload = aladin.temperature_payload(
            model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
            source_url="https://opendata.shmu.sk/example.grb",
            source_run_id="aladin-20260613-1200",
            values=[(0, 294.655), (1, None)],
        )
        rows = forecast.parse_helper_forecast(payload)

        self.assertEqual(payload["model_run_time"], "2026-06-13T12:00:00Z")
        self.assertEqual(payload["rows"][0]["valid_time"], "2026-06-13T12:00:00Z")
        self.assertEqual(payload["rows"][0]["temperature"], 21.505)
        self.assertIsNone(payload["rows"][1]["temperature"])
        self.assertEqual(rows[0].temperature, 21.505)
        self.assertIsNone(rows[1].temperature)

    def test_temperature_payload_from_grib_leads_decodes_temperature_fields(self):
        aladin = _load_module("aladin")
        forecast = _load_module("forecast")

        payload = aladin.temperature_payload_from_grib_leads(
            model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
            source_url="https://opendata.shmu.sk/run/",
            source_run_id="aladin-20260613-1200",
            latitude=47.74175,
            longitude=16.849607,
            grib_leads=[
                (0, _temperature_message(0, 294.655)),
                (1, _temperature_message(1, 295.155)),
            ],
        )
        rows = forecast.parse_helper_forecast(payload)

        self.assertEqual([row.lead_hours for row in rows], [0, 1])
        self.assertEqual([row.temperature for row in rows], [21.505, 22.005])

    def test_temperature_payload_rejects_naive_model_run_time(self):
        aladin = _load_module("aladin")

        with self.assertRaisesRegex(ValueError, "timezone"):
            aladin.temperature_payload(
                model_run_time=datetime(2026, 6, 13, 12),
                source_url="https://opendata.shmu.sk/example.grb",
                source_run_id="aladin-20260613-1200",
                values=[],
            )


if __name__ == "__main__":
    unittest.main()
