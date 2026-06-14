"""Small GRIB2 helpers used by the SHMU forecast downloader.

This is intentionally narrow. It supports only the simple-packing path needed
for the inspected ALADIN surface fields, without external GRIB dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
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
