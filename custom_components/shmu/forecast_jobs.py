"""Forecast cache executor job selection helpers."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .forecast_update import (
    update_forecast_cache_latest_aladin_temperature,
    update_forecast_cache_source,
)


def forecast_cache_update_job(
    cache_path: str | Path,
    *,
    source: str | None,
    now: datetime,
    latitude: float,
    longitude: float,
    verify_ssl: bool,
) -> Callable[[], dict[str, Any]]:
    """Return the executor job for helper-source or native ALADIN refresh."""
    if source:
        return partial(update_forecast_cache_source, cache_path, source)

    return partial(
        update_forecast_cache_latest_aladin_temperature,
        cache_path,
        now=now,
        latitude=latitude,
        longitude=longitude,
        verify_ssl=verify_ssl,
    )
