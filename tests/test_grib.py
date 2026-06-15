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

    def test_parse_grid_definition_reads_template_33_lambert_fields(self):
        grib = _load_grib()

        grid = grib.parse_grid_definition(_real_template_33_grid_section())

        self.assertEqual(grid.template, 33)
        self.assertEqual(grid.points, 4512)
        self.assertEqual(grid.nx, 94)
        self.assertEqual(grid.ny, 48)
        self.assertEqual(grid.latitude_first, 47741750)
        self.assertEqual(grid.longitude_first, 16849607)
        self.assertEqual(grid.latitude_d, 46244701)
        self.assertEqual(grid.longitude_v, 17000000)
        self.assertEqual(grid.dx, 4500000)
        self.assertEqual(grid.dy, 4500000)
        self.assertEqual(grid.scanning_mode, 64)
        self.assertEqual(grid.latin1, 46244701)
        self.assertEqual(grid.latin2, 46244701)
        self.assertEqual(grid.nux, 94)
        self.assertEqual(grid.nuy, 48)

    def test_lambert_grid_point_lat_lon_maps_template_33_scan_order(self):
        grib = _load_grib()
        grid = grib.parse_grid_definition(_real_template_33_grid_section())

        latitude, longitude = grib.lambert_grid_point_lat_lon(grid, 0, 0)
        east_latitude, east_longitude = grib.lambert_grid_point_lat_lon(grid, 1, 0)
        north_latitude, north_longitude = grib.lambert_grid_point_lat_lon(grid, 0, 1)

        self.assertAlmostEqual(latitude, 47.74175, places=5)
        self.assertAlmostEqual(longitude, 16.849607, places=5)
        self.assertGreater(east_longitude, longitude)
        self.assertGreater(north_latitude, latitude)
        self.assertAlmostEqual(east_latitude, latitude, places=1)
        self.assertAlmostEqual(north_longitude, longitude, places=1)

    def test_nearest_lambert_grid_point_returns_value_index(self):
        grib = _load_grib()
        grid = grib.parse_grid_definition(_real_template_33_grid_section())
        latitude, longitude = grib.lambert_grid_point_lat_lon(grid, 1, 1)

        point = grib.nearest_lambert_grid_point(grid, latitude, longitude)

        self.assertEqual(point.column, 1)
        self.assertEqual(point.row, 1)
        self.assertEqual(point.index, 95)
        self.assertAlmostEqual(point.latitude, latitude, places=7)
        self.assertAlmostEqual(point.longitude, longitude, places=7)
        self.assertLess(point.distance_m, 1)

    def test_decode_nearest_lambert_value_returns_point_value(self):
        grib = _load_grib()
        grid = grib.parse_grid_definition(_real_template_33_grid_section())
        latitude, longitude = grib.lambert_grid_point_lat_lon(grid, 1, 1)
        message = next(
            grib.iter_grib2_messages(
                _message(
                    [
                        _real_template_33_grid_section(),
                        _product_section(0, 0, 103, 2),
                        *_constant_grid_sections(),
                    ]
                )
            )
        )

        result = grib.decode_nearest_lambert_value(message, latitude, longitude)

        self.assertEqual(result.point.index, 95)
        self.assertEqual(result.value, 280.0)

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
