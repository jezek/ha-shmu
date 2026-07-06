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


if __name__ == "__main__":
    unittest.main()
