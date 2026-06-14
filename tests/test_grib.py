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


def _message(sections, discipline=0):
    body = b"".join(sections) + b"7777"
    length = len(body) + 16
    return b"GRIB" + b"\0\0" + bytes([discipline, 2]) + length.to_bytes(8, "big") + body


def _product_section(category, number, surface_type, surface_value, forecast_time=5):
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


def _grid_section(points=5, template=33):
    return _section(
        3,
        b"".join(
            [
                bytes([0]),
                points.to_bytes(4, "big"),
                bytes([0, 0]),
                template.to_bytes(2, "big"),
            ]
        ),
    )


def _simple_packing_sections():
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
    return section5, section6, section7


class TestGrib(unittest.TestCase):
    def test_iter_grib2_messages_reads_concatenated_messages(self):
        grib = _load_grib()
        first = _message([_section(1, b"a"), _section(4, b"temp")])
        second = _message([_section(1, b"b"), _section(4, b"wind")], discipline=2)

        messages = list(grib.iter_grib2_messages(first + second))

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].offset, 0)
        self.assertEqual(messages[0].length, len(first))
        self.assertEqual(messages[0].discipline, 0)
        self.assertEqual(messages[0].section(4), _section(4, b"temp"))
        self.assertEqual(messages[1].offset, len(first))
        self.assertEqual(messages[1].discipline, 2)
        self.assertEqual(messages[1].section(4), _section(4, b"wind"))

    def test_parse_product_definition_reads_selector_fields(self):
        grib = _load_grib()
        section4 = _product_section(0, 0, 103, 2)

        product = grib.parse_product_definition(section4)

        self.assertEqual(product.template, 0)
        self.assertEqual(product.parameter_category, 0)
        self.assertEqual(product.parameter_number, 0)
        self.assertEqual(product.forecast_time_unit, 1)
        self.assertEqual(product.forecast_time, 5)
        self.assertEqual(product.first_surface_type, 103)
        self.assertEqual(product.first_surface_scale_factor, 0)
        self.assertEqual(product.first_surface_scaled_value, 2)
        self.assertEqual(product.second_surface_type, 255)

    def test_parse_grid_definition_reads_points_and_template(self):
        grib = _load_grib()

        grid = grib.parse_grid_definition(_grid_section(points=4512))

        self.assertEqual(grid.template, 33)
        self.assertEqual(grid.points, 4512)

    def test_find_product_message_selects_requested_field(self):
        grib = _load_grib()
        wind = _message([_section(1, b"wind"), _product_section(2, 2, 103, 10)])
        temperature = _message([_section(1, b"temp"), _product_section(0, 0, 103, 2)])
        messages = list(grib.iter_grib2_messages(wind + temperature))

        match = grib.find_product_message(
            messages,
            discipline=0,
            parameter_category=0,
            parameter_number=0,
            first_surface_type=103,
            first_surface_scaled_value=2,
            forecast_time=5,
        )

        self.assertIs(match, messages[1])
        self.assertIsNone(
            grib.find_product_message(
                messages,
                discipline=0,
                parameter_category=0,
                parameter_number=0,
                first_surface_type=103,
                first_surface_scaled_value=2,
                forecast_time=6,
            )
        )

    def test_decode_simple_packing_grid_expands_bitmap(self):
        grib = _load_grib()
        section5, section6, section7 = _simple_packing_sections()

        self.assertEqual(
            grib.decode_simple_packing_grid(section5, section6, section7, 5),
            [1.2, None, 1.4, 1.6, None],
        )

    def test_decode_message_grid_uses_section3_point_count(self):
        grib = _load_grib()
        message = next(
            grib.iter_grib2_messages(
                _message([_grid_section(), _product_section(0, 0, 103, 2), *_simple_packing_sections()])
            )
        )

        self.assertEqual(grib.decode_message_grid(message), [1.2, None, 1.4, 1.6, None])

    def test_grib_signed_int_uses_sign_and_magnitude(self):
        grib = _load_grib()

        self.assertEqual(grib.grib_signed_int(bytes.fromhex("800d")), -13)
        self.assertEqual(grib.grib_signed_int(bytes.fromhex("0032")), 50)


if __name__ == "__main__":
    unittest.main()
