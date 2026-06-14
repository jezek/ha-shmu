import importlib.util
from pathlib import Path
import struct
import sys
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "grib.py"
)


def _load_grib():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.grib",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pack_bits(values, width):
    bits = "".join(f"{value:0{width}b}" for value in values)
    bits += "0" * ((8 - len(bits) % 8) % 8)
    return bytes(int(bits[index : index + 8], 2) for index in range(0, len(bits), 8))


def _section(number, payload):
    return (len(payload) + 5).to_bytes(4, "big") + bytes([number]) + payload


class TestGrib(unittest.TestCase):
    def test_decode_simple_packing_grid_expands_bitmap(self):
        grib = _load_grib()
        section5 = _section(
            5,
            b"".join(
                [
                    (3).to_bytes(4, "big"),
                    (0).to_bytes(2, "big"),
                    struct.pack(">f", 10.0),
                    (1).to_bytes(2, "big"),
                    (1).to_bytes(2, "big"),
                    bytes([3, 0]),
                ]
            ),
        )
        section6 = _section(6, bytes([0]) + _pack_bits([1, 0, 1, 1, 0], 1))
        section7 = _section(7, _pack_bits([1, 2, 3], 3))

        self.assertEqual(
            grib.decode_simple_packing_grid(section5, section6, section7, 5),
            [1.2, None, 1.4, 1.6, None],
        )

    def test_grib_signed_int_uses_sign_and_magnitude(self):
        grib = _load_grib()

        self.assertEqual(grib.grib_signed_int(bytes.fromhex("800d")), -13)
        self.assertEqual(grib.grib_signed_int(bytes.fromhex("0032")), 50)


if __name__ == "__main__":
    unittest.main()
