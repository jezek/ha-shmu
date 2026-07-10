import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "forecast_update.py"
)


def _load_forecast_update():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.forecast_update",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _payload(source_run_id="run-1", temperature=17.2):
    return {
        "model_run_time": "2026-06-03T00:00:00Z",
        "source_url": "https://example.test/cache.json",
        "source_run_id": source_run_id,
        "rows": [{"valid_time": "2026-06-03T01:00:00Z", "temperature": temperature}],
    }


def _json_response(payload):
    return _Response(json.dumps(payload).encode("utf-8"))


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


def _temperature_message(lead_hours, value):
    section5 = _section(
        5,
        b"".join(
            [
                (4512).to_bytes(4, "big"),
                (0).to_bytes(2, "big"),
                struct.pack(">f", value),
                (0).to_bytes(2, "big"),
                (0).to_bytes(2, "big"),
                bytes([0, 0]),
            ]
        ),
    )
    return _message(
        [
            _real_template_33_grid_section(),
            _product_section(0, 0, 103, 2, lead_hours),
            section5,
            _section(6, bytes([255])),
            _section(7, b""),
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


class TestForecastUpdate(unittest.TestCase):
    def test_update_forecast_cache_payload_writes_new_cache(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            result = forecast_update.update_forecast_cache_payload(
                cache_path,
                _payload(),
            )
            written = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(result["info"]["source_run_id"], "run-1")
        self.assertEqual(written["source_run_id"], "run-1")

    def test_update_forecast_cache_payload_skips_unchanged_run_id(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            forecast_update.update_forecast_cache_payload(cache_path, _payload())
            original_mtime = 1_780_000_000
            os.utime(cache_path, (original_mtime, original_mtime))

            result = forecast_update.update_forecast_cache_payload(
                cache_path,
                _payload(temperature=22.5),
            )
            stat = cache_path.stat()

        self.assertFalse(result["changed"])
        self.assertEqual(stat.st_mtime, original_mtime)

    def test_update_forecast_cache_payload_rejects_invalid_payload(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            with self.assertRaisesRegex(ValueError, "missing required field"):
                forecast_update.update_forecast_cache_payload(cache_path, {"rows": []})

        self.assertFalse(cache_path.exists())

    def test_update_forecast_cache_source_reads_local_helper_payload(self):
        forecast_update = _load_forecast_update()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "source.json"
            cache_path = temp_path / "forecast-cache.json"
            source_path.write_text(json.dumps(_payload("run-2")), encoding="utf-8")

            result = forecast_update.update_forecast_cache_source(
                cache_path,
                str(source_path),
            )

        self.assertTrue(result["changed"])
        self.assertEqual(result["info"]["source_run_id"], "run-2")

    def test_update_forecast_cache_aladin_temperature_downloads_and_writes_cache(self):
        forecast_update = _load_forecast_update()
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            lead = int(request.full_url.split("al-grib_sk_")[1].split("-", 1)[0])
            return _Response(_temperature_message(lead, 294.655 + lead))

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            result = forecast_update.update_forecast_cache_aladin_temperature(
                cache_path,
                model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
                latitude=47.74175,
                longitude=16.849607,
                lead_hours=[0, 1],
                timeout=4,
                opener=opener,
            )
            written = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(written["source_run_id"], "aladin-sk-4.5km-20260613-1200")
        self.assertEqual([row["temperature"] for row in written["rows"]], [21.505, 22.505])
        self.assertEqual([timeout for _, timeout in calls], [4, 4])

    def test_update_forecast_cache_aladin_temperature_uses_default_leads(self):
        forecast_update = _load_forecast_update()
        calls = []

        def opener(request, timeout):
            lead = int(request.full_url.split("al-grib_sk_")[1].split("-", 1)[0])
            calls.append(lead)
            return _Response(_temperature_message(lead, 294.655 + lead))

        with tempfile.TemporaryDirectory() as temp_dir:
            forecast_update.update_forecast_cache_aladin_temperature(
                Path(temp_dir) / "forecast-cache.json",
                model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
                latitude=47.74175,
                longitude=16.849607,
                opener=opener,
            )

        self.assertEqual(calls, list(range(79)))

    def test_update_forecast_cache_aladin_temperature_skips_unchanged_run(self):
        forecast_update = _load_forecast_update()

        def opener(request, timeout):
            self.fail("unchanged ALADIN run should not download GRIB leads")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            forecast_update.update_forecast_cache_payload(
                cache_path,
                _payload("aladin-sk-4.5km-20260613-1200"),
            )
            original_mtime = 1_780_000_000
            os.utime(cache_path, (original_mtime, original_mtime))

            result = forecast_update.update_forecast_cache_aladin_temperature(
                cache_path,
                model_run_time=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
                latitude=47.74175,
                longitude=16.849607,
                lead_hours=[0],
                opener=opener,
            )
            unchanged_mtime = cache_path.stat().st_mtime

        self.assertFalse(result["changed"])
        self.assertEqual(unchanged_mtime, original_mtime)

    def test_update_forecast_cache_latest_aladin_temperature_selects_latest_run(self):
        forecast_update = _load_forecast_update()
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return _Response(_temperature_message(0, 294.655))

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            result = forecast_update.update_forecast_cache_latest_aladin_temperature(
                cache_path,
                now=datetime(2026, 6, 16, 20, 2, tzinfo=timezone.utc),
                latitude=47.74175,
                longitude=16.849607,
                lead_hours=[0],
                opener=opener,
            )
            written = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(written["source_run_id"], "aladin-sk-4.5km-20260616-1200")
        self.assertIn("/20260616/1200/al-grib_sk_000-20260616-1200-", calls[0])

    def test_update_forecast_cache_latest_ecmwf_epsgram_writes_cache(self):
        forecast_update = _load_forecast_update()
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            if request.full_url.endswith("getstationproducts?station=31396"):
                return _json_response(
                    {
                        "data": [
                            {
                                "type": "aladin",
                                "runtime": 1783306800,
                                "file_link": "aladin/2026-07-06/31396.json",
                            },
                            {
                                "type": "ecmwf",
                                "runtime": 1783296000,
                                "file_link": "ecmwf/2026-07-06/31396_2026-07-06_00.json",
                            },
                        ]
                    }
                )
            return _json_response(
                {
                    "data_date_time": "2026-07-06T00:00Z",
                    "si_id": "31396",
                    "Air_temperature_at_2m": {
                        "columns": [
                            "Time",
                            "Minimum",
                            "Lower quartile",
                            "Median",
                            "Upper quartile",
                            "Maximum",
                        ],
                        "data": [[1783296000, 16.0, 16.9, 17.592, 18.0, 18.9]],
                    },
                    "Total_cloud_cover": {
                        "columns": [
                            "Time",
                            "Minimum",
                            "Lower quartile",
                            "Median",
                            "Upper quartile",
                            "Maximum",
                        ],
                        "data": [[1783296000, 24.7, 37.0, 47.745, 61.0, 87.8]],
                    },
                }
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"

            result = forecast_update.update_forecast_cache_latest_ecmwf_epsgram(
                cache_path,
                station_id="31396",
                timeout=5,
                opener=opener,
            )
            written = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(written["source_run_id"], "ecmwf-31396-2026-07-06T00:00:00Z")
        self.assertEqual(written["source_url"], calls[1][0])
        self.assertEqual(written["rows"][0]["temperature"], 17.592)
        self.assertEqual(written["rows"][0]["cloud_cover"], 47.745)
        self.assertEqual([timeout for _, timeout in calls], [5, 5])


if __name__ == "__main__":
    unittest.main()
