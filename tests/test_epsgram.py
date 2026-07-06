import importlib.util
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "epsgram.py"
)


def _load_epsgram():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.epsgram",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestEPSGRAM(unittest.TestCase):
    def test_latest_station_product_selects_newest_type(self):
        epsgram = _load_epsgram()
        payload = {
            "data": [
                {
                    "type": "ecmwf",
                    "runtime": 1783209600,
                    "file_link": "ecmwf/2026-07-05/31396_2026-07-05_00.json",
                },
                {
                    "type": "aladin",
                    "runtime": 1783274400,
                    "file_link": "aladin/2026-07-05/31396_2026-07-05_18.json",
                },
                {
                    "type": "ecmwf",
                    "runtime": 1783296000,
                    "file_link": "ecmwf/2026-07-06/31396_2026-07-06_00.json",
                },
            ]
        }

        product = epsgram.latest_station_product(payload, "ecmwf")

        self.assertEqual(
            product["file_link"],
            "ecmwf/2026-07-06/31396_2026-07-06_00.json",
        )

    def test_latest_station_product_rejects_missing_type(self):
        epsgram = _load_epsgram()

        with self.assertRaisesRegex(ValueError, "no station product"):
            epsgram.latest_station_product({"data": []}, "ecmwf")

    def test_product_json_url_uses_station_product_link(self):
        epsgram = _load_epsgram()

        self.assertEqual(
            epsgram.product_json_url("/ecmwf/2026-07-06/file.json"),
            "https://www.shmu.sk/data/datanwp/json/ecmwf/2026-07-06/file.json",
        )

    def test_ecmwf_helper_payload_normalizes_median_rows(self):
        epsgram = _load_epsgram()
        payload = {
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
                "data": [
                    [1783296000, 16.0, 16.9, 17.592, 18.0, 18.9],
                    [1783306800, 15.0, 15.8, 16.087, 16.3, 17.3],
                ],
            },
            "Total_precipitation": {
                "columns": [
                    "Time",
                    "Minimum",
                    "Lower quartile",
                    "Median",
                    "Upper quartile",
                    "Maximum",
                ],
                "data": [[1783306800, 0.0, 0.1, 0.346, 0.5, 1.7]],
            },
            "Wind_speed_at_10m": {
                "columns": [
                    "Time",
                    "Minimum",
                    "Lower quartile",
                    "Median",
                    "Upper quartile",
                    "Maximum",
                ],
                "data": [[1783296000, 1.0, 1.7, 2.086, 2.5, 3.4]],
            },
            "Wind_direction_at_10m": {
                "columns": ["Time", "N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                "data": [[1783296000, 0, 0, 0, 0, 0, 0, 26, 25]],
            },
        }

        result = epsgram.ecmwf_helper_payload(
            payload,
            "https://www.shmu.sk/data/datanwp/json/ecmwf/file.json",
        )

        self.assertEqual(result["model_run_time"], "2026-07-06T00:00:00Z")
        self.assertEqual(result["source_run_id"], "ecmwf-31396-2026-07-06T00:00:00Z")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(
            result["rows"][0],
            {
                "valid_time": "2026-07-06T00:00:00Z",
                "lead_hours": 0.0,
                "temperature": 17.592,
                "pressure": None,
                "wind_speed": 2.086,
                "wind_gust": None,
                "cloud_cover": None,
                "precipitation_amount": None,
                "wind_direction": 270.0,
            },
        )
        self.assertEqual(result["rows"][1]["valid_time"], "2026-07-06T03:00:00Z")
        self.assertEqual(result["rows"][1]["lead_hours"], 3.0)
        self.assertEqual(result["rows"][1]["temperature"], 16.087)
        self.assertEqual(result["rows"][1]["precipitation_amount"], 0.346)

    def test_ecmwf_helper_payload_rejects_missing_temperature_medians(self):
        epsgram = _load_epsgram()

        with self.assertRaisesRegex(ValueError, "temperature median rows"):
            epsgram.ecmwf_helper_payload(
                {"data_date_time": "2026-07-06T00:00Z"},
                "https://www.shmu.sk/data/datanwp/json/ecmwf/file.json",
            )


if __name__ == "__main__":
    unittest.main()
