"""SHMU ALADIN forecast normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from .grib import decode_nearest_lambert_value, find_product_message, iter_grib2_messages

KELVIN_OFFSET = 273.15
TEMPERATURE_2M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 0,
    "parameter_number": 0,
    "first_surface_type": 103,
    "first_surface_scaled_value": 2,
}


def temperature_payload(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    values: Iterable[tuple[int, float | None]],
) -> dict[str, Any]:
    """Build helper-compatible forecast JSON from ALADIN 2 m temperatures."""
    model_run_time = _as_utc(model_run_time)
    rows: list[dict[str, Any]] = []
    for lead_hours, temperature_k in values:
        valid_time = model_run_time + timedelta(hours=lead_hours)
        rows.append(
            {
                "valid_time": _format_utc(valid_time),
                "lead_hours": lead_hours,
                "temperature": None
                if temperature_k is None
                else round(temperature_k - KELVIN_OFFSET, 3),
            }
        )

    return {
        "model_run_time": _format_utc(model_run_time),
        "source_url": source_url,
        "source_run_id": source_run_id,
        "rows": rows,
    }


def temperature_payload_from_grib_leads(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    latitude: float,
    longitude: float,
    grib_leads: Iterable[tuple[int, bytes]],
) -> dict[str, Any]:
    """Build helper-compatible temperature JSON from ALADIN GRIB lead files."""
    values: list[tuple[int, float | None]] = []
    for lead_hours, data in grib_leads:
        message = find_product_message(
            iter_grib2_messages(data),
            forecast_time=lead_hours,
            **TEMPERATURE_2M_SELECTOR,
        )
        if message is None:
            raise ValueError(f"missing 2 m temperature field for lead {lead_hours}")
        value = decode_nearest_lambert_value(message, latitude, longitude)
        values.append((lead_hours, value.value))

    return temperature_payload(
        model_run_time=model_run_time,
        source_url=source_url,
        source_run_id=source_run_id,
        values=values,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("model_run_time must include timezone")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
