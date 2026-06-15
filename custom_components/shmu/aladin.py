"""SHMU ALADIN forecast normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

KELVIN_OFFSET = 273.15


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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("model_run_time must include timezone")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
