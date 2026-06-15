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


class _Response:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._data


class TestAladin(unittest.TestCase):
    def test_grib_url_formats_opendata_aladin_lead_url(self):
        aladin = _load_module("aladin")

        self.assertEqual(
            aladin.grib_url(
                datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
                7,
            ),
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km/"
            "20260613/1200/al-grib_sk_007-20260613-1200-nwp-.grb",
        )

    def test_run_metadata_formats_stable_run_id_and_url(self):
        aladin = _load_module("aladin")

        model_run_time = datetime(2026, 6, 13, 12, tzinfo=timezone.utc)

        self.assertEqual(
            aladin.run_id(model_run_time),
            "aladin-sk-4.5km-20260613-1200",
        )
        self.assertEqual(
            aladin.run_url(model_run_time),
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km/"
            "20260613/1200",
        )

    def test_grib_url_rejects_negative_lead_hours(self):
        aladin = _load_module("aladin")

        with self.assertRaisesRegex(ValueError, "negative"):
            aladin.grib_url(datetime(2026, 6, 13, 12, tzinfo=timezone.utc), -1)

    def test_download_grib_lead_uses_opendata_url_and_user_agent(self):
        aladin = _load_module("aladin")
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _Response(b"GRIB")

        lead_hours, data = aladin.download_grib_lead(
            datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
            7,
            timeout=5,
            opener=opener,
        )

        self.assertEqual(lead_hours, 7)
        self.assertEqual(data, b"GRIB")
        self.assertEqual(calls[0][1], 5)
        self.assertEqual(
            calls[0][0].full_url,
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km/"
            "20260613/1200/al-grib_sk_007-20260613-1200-nwp-.grb",
        )
        self.assertEqual(calls[0][0].get_header("User-agent"), "ha-shmu-aladin/1.0")

    def test_download_grib_leads_downloads_each_requested_lead(self):
        aladin = _load_module("aladin")
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            lead = request.full_url.split("al-grib_sk_")[1].split("-", 1)[0]
            return _Response(f"lead-{lead}".encode())

        leads = aladin.download_grib_leads(
            datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
            [0, 3, 7],
            timeout=6,
            opener=opener,
        )

        self.assertEqual(
            leads,
            [
                (0, b"lead-000"),
                (3, b"lead-003"),
                (7, b"lead-007"),
            ],
        )
        self.assertEqual([timeout for _, timeout in calls], [6, 6, 6])
        self.assertEqual(
            [url.split("al-grib_sk_")[1].split("-", 1)[0] for url, _ in calls],
            ["000", "003", "007"],
        )

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
