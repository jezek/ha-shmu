"""Small GRIB2 helpers used by the SHMU forecast downloader.

This is intentionally narrow. It supports only the simple-packing path needed
for the inspected ALADIN surface fields, without external GRIB dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
import struct


@dataclass(frozen=True)
class Grib2Message:
    """One GRIB2 message extracted from a concatenated GRIB file."""

    offset: int
    length: int
    discipline: int
    sections: dict[int, bytes]

    def section(self, number: int) -> bytes:
        """Return a required section by number."""
        try:
            return self.sections[number]
        except KeyError as err:
            raise ValueError(f"missing GRIB2 section {number}") from err


@dataclass(frozen=True)
class ProductDefinition:
    """GRIB2 product metadata used to select forecast fields."""

    template: int
    parameter_category: int
    parameter_number: int
    forecast_time_unit: int
    forecast_time: int
    first_surface_type: int
    first_surface_scale_factor: int | None
    first_surface_scaled_value: int | None
    second_surface_type: int


@dataclass(frozen=True)
class GridDefinition:
    """GRIB2 grid metadata needed for value expansion."""

    template: int
    points: int
    nx: int | None = None
    ny: int | None = None
    latitude_first: int | None = None
    longitude_first: int | None = None
    resolution_flags: int | None = None
    latitude_d: int | None = None
    longitude_v: int | None = None
    dx: int | None = None
    dy: int | None = None
    projection_centre_flags: int | None = None
    scanning_mode: int | None = None
    latin1: int | None = None
    latin2: int | None = None
    southern_pole_latitude: int | None = None
    southern_pole_longitude: int | None = None
    nux: int | None = None
    ncx: int | None = None
    nuy: int | None = None
    ncy: int | None = None


@dataclass(frozen=True)
class GridPoint:
    """One decoded grid point selected from a GRIB grid."""

    column: int
    row: int
    index: int
    latitude: float
    longitude: float
    distance_m: float


@dataclass(frozen=True)
class GridPointValue:
    """A decoded GRIB value at a selected grid point."""

    point: GridPoint
    value: float | None


def iter_grib2_messages(data: bytes):
    """Yield GRIB2 messages from a possibly concatenated GRIB byte stream."""
    position = 0
    while position < len(data):
        start = data.find(b"GRIB", position)
        if start == -1:
            return
        if start + 16 > len(data):
            raise ValueError("truncated GRIB2 indicator section")
        edition = data[start + 7]
        if edition != 2:
            raise ValueError(f"unsupported GRIB edition: {edition}")
        length = int.from_bytes(data[start + 8 : start + 16], "big")
        end = start + length
        if length < 20 or end > len(data):
            raise ValueError("invalid GRIB2 message length")
        if data[end - 4 : end] != b"7777":
            raise ValueError("missing GRIB2 end marker")

        sections: dict[int, bytes] = {}
        section_position = start + 16
        while section_position < end - 4:
            if section_position + 5 > end - 4:
                raise ValueError("truncated GRIB2 section header")
            section_length = int.from_bytes(data[section_position : section_position + 4], "big")
            section_number = data[section_position + 4]
            section_end = section_position + section_length
            if section_length < 5 or section_end > end - 4:
                raise ValueError("invalid GRIB2 section length")
            sections[section_number] = data[section_position:section_end]
            section_position = section_end

        yield Grib2Message(
            offset=start,
            length=length,
            discipline=data[start + 6],
            sections=sections,
        )
        position = end


def parse_grid_definition(section3: bytes) -> GridDefinition:
    """Parse GRIB2 section 3 grid metadata needed by the narrow decoder."""
    if len(section3) < 14 or section3[4] != 3:
        raise ValueError("section 3 is not a valid GRIB2 grid definition section")
    template = int.from_bytes(section3[12:14], "big")
    points = int.from_bytes(section3[6:10], "big")
    if template == 33 and len(section3) >= 97:
        return GridDefinition(
            template=template,
            points=points,
            nx=_uint(section3, 30, 34),
            ny=_uint(section3, 34, 38),
            latitude_first=_grib_signed_slice(section3, 38, 42),
            longitude_first=_grib_signed_slice(section3, 42, 46),
            resolution_flags=section3[46],
            latitude_d=_grib_signed_slice(section3, 47, 51),
            longitude_v=_grib_signed_slice(section3, 51, 55),
            dx=_uint(section3, 55, 59),
            dy=_uint(section3, 59, 63),
            projection_centre_flags=section3[63],
            scanning_mode=section3[64],
            latin1=_grib_signed_slice(section3, 65, 69),
            latin2=_grib_signed_slice(section3, 69, 73),
            southern_pole_latitude=_grib_signed_slice(section3, 73, 77),
            southern_pole_longitude=_grib_signed_slice(section3, 77, 81),
            nux=_uint(section3, 81, 85),
            ncx=_uint(section3, 85, 89),
            nuy=_uint(section3, 89, 93),
            ncy=_uint(section3, 93, 97),
        )
    return GridDefinition(template=template, points=points)


def parse_product_definition(section4: bytes) -> ProductDefinition:
    """Parse the common GRIB2 product definition fields from section 4."""
    if len(section4) < 29 or section4[4] != 4:
        raise ValueError("section 4 is not a valid GRIB2 product definition section")
    template = int.from_bytes(section4[7:9], "big")
    if template not in {0, 8}:
        raise ValueError(f"unsupported GRIB2 product definition template: {template}")

    return ProductDefinition(
        template=template,
        parameter_category=section4[9],
        parameter_number=section4[10],
        forecast_time_unit=section4[17],
        forecast_time=int.from_bytes(section4[18:22], "big", signed=True),
        first_surface_type=section4[22],
        first_surface_scale_factor=_optional_grib_signed_int(section4[23:24]),
        first_surface_scaled_value=_optional_grib_signed_int(section4[24:28]),
        second_surface_type=section4[28],
    )


def find_product_message(
    messages: Iterable[Grib2Message],
    *,
    discipline: int,
    parameter_category: int,
    parameter_number: int,
    first_surface_type: int,
    first_surface_scaled_value: int | None = None,
    forecast_time: int | None = None,
) -> Grib2Message | None:
    """Return the first message matching the requested product selector."""
    for message in messages:
        if message.discipline != discipline:
            continue
        try:
            product = parse_product_definition(message.section(4))
        except ValueError:
            continue
        if product.parameter_category != parameter_category:
            continue
        if product.parameter_number != parameter_number:
            continue
        if product.first_surface_type != first_surface_type:
            continue
        if first_surface_scaled_value is not None:
            if product.first_surface_scaled_value != first_surface_scaled_value:
                continue
        if forecast_time is not None and product.forecast_time != forecast_time:
            continue
        return message
    return None


def decode_message_grid(message: Grib2Message) -> list[float | None]:
    """Decode a selected simple-packing message into a full grid-value array."""
    grid = parse_grid_definition(message.section(3))
    return decode_simple_packing_grid(
        message.section(5),
        message.section(6),
        message.section(7),
        grid.points,
    )


def decode_nearest_lambert_value(
    message: Grib2Message,
    latitude: float,
    longitude: float,
) -> GridPointValue:
    """Decode a message and return the value nearest to a latitude/longitude."""
    grid = parse_grid_definition(message.section(3))
    point = nearest_lambert_grid_point(grid, latitude, longitude)
    values = decode_message_grid(message)
    if point.index >= len(values):
        raise ValueError("nearest grid point is outside decoded value array")
    return GridPointValue(point=point, value=values[point.index])


def lambert_grid_point_lat_lon(
    grid: GridDefinition,
    column: int,
    row: int,
) -> tuple[float, float]:
    """Return latitude/longitude degrees for a GRIB template 3.33 grid point."""
    _require_template_33_coordinates(grid)
    if column < 0 or row < 0 or column >= grid.nx or row >= grid.ny:
        raise ValueError("grid point is outside the GRIB grid")

    radius = 6371229.0
    lat_first = _degrees_from_microdegrees(grid.latitude_first)
    lon_first = _degrees_from_microdegrees(grid.longitude_first)
    lon_origin = _degrees_from_microdegrees(grid.longitude_v)
    latin1 = _degrees_from_microdegrees(grid.latin1)
    latin2 = _degrees_from_microdegrees(grid.latin2)

    x_first, y_first, projection = _lambert_forward(
        lat_first,
        lon_first,
        lon_origin,
        latin1,
        latin2,
        radius,
    )
    x_sign = -1 if grid.scanning_mode & 0x80 else 1
    y_sign = 1 if grid.scanning_mode & 0x40 else -1
    x = x_first + x_sign * column * _grid_length_meters(grid.dx)
    y = y_first + y_sign * row * _grid_length_meters(grid.dy)
    return _lambert_inverse(x, y, lon_origin, projection)


def nearest_lambert_grid_point(
    grid: GridDefinition,
    latitude: float,
    longitude: float,
) -> GridPoint:
    """Return the nearest template 3.33 grid point for a latitude/longitude."""
    _require_template_33_coordinates(grid)
    nearest: GridPoint | None = None
    for row in range(grid.ny):
        for column in range(grid.nx):
            point_latitude, point_longitude = lambert_grid_point_lat_lon(
                grid,
                column,
                row,
            )
            distance_m = _haversine_meters(
                latitude,
                longitude,
                point_latitude,
                point_longitude,
            )
            if nearest is None or distance_m < nearest.distance_m:
                nearest = GridPoint(
                    column=column,
                    row=row,
                    index=row * grid.nx + column,
                    latitude=point_latitude,
                    longitude=point_longitude,
                    distance_m=distance_m,
                )
    if nearest is None:
        raise ValueError("GRIB grid contains no points")
    return nearest


def decode_simple_packing_grid(
    section5: bytes,
    section6: bytes,
    section7: bytes,
    grid_points: int,
) -> list[float | None]:
    """Decode GRIB2 template 5.0 values and expand an optional bitmap."""
    if len(section5) < 21 or section5[4] != 5:
        raise ValueError("section 5 is not a valid GRIB2 data representation section")
    if len(section7) < 5 or section7[4] != 7:
        raise ValueError("section 7 is not a valid GRIB2 data section")

    packed_points = int.from_bytes(section5[5:9], "big")
    template = int.from_bytes(section5[9:11], "big")
    if template != 0:
        raise ValueError(f"unsupported GRIB2 data representation template: {template}")

    reference_value = struct.unpack(">f", section5[11:15])[0]
    binary_scale = grib_signed_int(section5[15:17])
    decimal_scale = grib_signed_int(section5[17:19])
    bits_per_value = section5[19]

    packed = _read_unsigned_bits(section7[5:], bits_per_value, packed_points)
    values = [
        (reference_value + raw * (2**binary_scale)) / (10**decimal_scale)
        for raw in packed
    ]

    if _section6_has_bitmap(section6):
        bitmap = _read_bitmap(section6[6:], grid_points)
        if sum(bitmap) != packed_points:
            raise ValueError("GRIB2 bitmap present count does not match packed value count")
        expanded: list[float | None] = []
        value_index = 0
        for present in bitmap:
            if present:
                expanded.append(values[value_index])
                value_index += 1
            else:
                expanded.append(None)
        return expanded

    if packed_points != grid_points:
        raise ValueError("packed value count does not match grid point count")
    return values


def grib_signed_int(raw: bytes) -> int:
    """Decode a GRIB sign-and-magnitude signed integer."""
    if not raw:
        raise ValueError("missing GRIB signed integer bytes")
    value = int.from_bytes(raw, "big")
    sign_bit = 1 << (len(raw) * 8 - 1)
    magnitude = value & (sign_bit - 1)
    return -magnitude if value & sign_bit else magnitude


def _optional_grib_signed_int(raw: bytes) -> int | None:
    if all(byte == 0xFF for byte in raw):
        return None
    return grib_signed_int(raw)


def _uint(data: bytes, start: int, end: int) -> int:
    return int.from_bytes(data[start:end], "big")


def _grib_signed_slice(data: bytes, start: int, end: int) -> int:
    return grib_signed_int(data[start:end])


def _section6_has_bitmap(section6: bytes) -> bool:
    if len(section6) < 6 or section6[4] != 6:
        raise ValueError("section 6 is not a valid GRIB2 bitmap section")
    indicator = section6[5]
    if indicator == 0:
        return True
    if indicator == 255:
        return False
    raise ValueError(f"unsupported GRIB2 bitmap indicator: {indicator}")


def _read_bitmap(data: bytes, count: int) -> list[bool]:
    if len(data) * 8 < count:
        raise ValueError("not enough bitmap data")
    return [bool((data[index // 8] >> (7 - index % 8)) & 1) for index in range(count)]


def _read_unsigned_bits(data: bytes, width: int, count: int) -> list[int]:
    if width == 0:
        return [0] * count
    if width < 0:
        raise ValueError("bit width must not be negative")
    if len(data) * 8 < width * count:
        raise ValueError("not enough packed data")

    values: list[int] = []
    bitpos = 0
    for _ in range(count):
        value = 0
        for _ in range(width):
            byte = data[bitpos // 8]
            bit = (byte >> (7 - bitpos % 8)) & 1
            value = (value << 1) | bit
            bitpos += 1
        values.append(value)
    return values


def _require_template_33_coordinates(grid: GridDefinition) -> None:
    if grid.template != 33:
        raise ValueError(f"unsupported coordinate grid template: {grid.template}")
    required = [
        grid.nx,
        grid.ny,
        grid.latitude_first,
        grid.longitude_first,
        grid.longitude_v,
        grid.dx,
        grid.dy,
        grid.scanning_mode,
        grid.latin1,
        grid.latin2,
    ]
    if any(value is None for value in required):
        raise ValueError("GRIB template 3.33 coordinate fields are incomplete")


def _degrees_from_microdegrees(value: int | None) -> float:
    if value is None:
        raise ValueError("missing GRIB coordinate value")
    return value / 1_000_000


def _grid_length_meters(value: int | None) -> float:
    if value is None:
        raise ValueError("missing GRIB grid length value")
    return value / 1000


def _lambert_forward(
    latitude: float,
    longitude: float,
    longitude_origin: float,
    latin1: float,
    latin2: float,
    radius: float,
) -> tuple[float, float, tuple[float, float, float]]:
    phi = math.radians(latitude)
    lam = math.radians(longitude)
    lam0 = math.radians(longitude_origin)
    phi1 = math.radians(latin1)
    phi2 = math.radians(latin2)
    n = _lambert_n(phi1, phi2)
    factor = math.cos(phi1) * math.tan(math.pi / 4 + phi1 / 2) ** n / n
    rho = radius * factor / math.tan(math.pi / 4 + phi / 2) ** n
    theta = n * (lam - lam0)
    return rho * math.sin(theta), -rho * math.cos(theta), (n, factor, radius)


def _lambert_inverse(
    x: float,
    y: float,
    longitude_origin: float,
    projection: tuple[float, float, float],
) -> tuple[float, float]:
    n, factor, radius = projection
    rho = math.hypot(x, -y)
    theta = math.atan2(x, -y)
    phi = 2 * math.atan((radius * factor / rho) ** (1 / n)) - math.pi / 2
    lam = math.radians(longitude_origin) + theta / n
    return math.degrees(phi), math.degrees(lam)


def _lambert_n(phi1: float, phi2: float) -> float:
    if abs(phi1 - phi2) < 1e-12:
        return math.sin(phi1)
    numerator = math.log(math.cos(phi1) / math.cos(phi2))
    denominator = math.log(
        math.tan(math.pi / 4 + phi2 / 2) / math.tan(math.pi / 4 + phi1 / 2)
    )
    return numerator / denominator


def _haversine_meters(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    radius = 6371229.0
    phi1 = math.radians(latitude1)
    phi2 = math.radians(latitude2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(longitude2 - longitude1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
