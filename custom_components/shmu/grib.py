"""Small GRIB2 helpers used by the SHMU forecast downloader.

This is intentionally narrow. It supports only the simple-packing path needed
for the inspected ALADIN surface fields, without external GRIB dependencies.
"""

from __future__ import annotations

import struct


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
