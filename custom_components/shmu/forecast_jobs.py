"""Forecast cache executor job selection helpers."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .forecast_update import (
    leading_day_aladin_temperature_fallback,
    update_forecast_cache_latest_ecmwf_meteogram,
    update_forecast_cache_latest_aladin_temperature,
    update_forecast_cache_source,
)


def leading_day_aladin_fallback_job(
    *,
    model_run_time: datetime,
    latitude: float,
    longitude: float,
    verify_ssl: bool,
) -> Callable[[], dict[str, Any]]:
    """Return an executor job for a validated leading-day ALADIN fallback."""
    return partial(
        leading_day_aladin_temperature_fallback,
        model_run_time=model_run_time,
        latitude=latitude,
        longitude=longitude,
        verify_ssl=verify_ssl,
    )


def forecast_cache_update_job(
    cache_path: str | Path,
    *,
    source: str | None,
    now: datetime,
    latitude: float,
    longitude: float,
    verify_ssl: bool,
    force_refresh: bool = False,
) -> Callable[[], dict[str, Any]]:
    """Return the executor job for helper-source or native ALADIN refresh."""
    if source:
        return partial(
            update_forecast_cache_source,
            cache_path,
            source,
            force_refresh=force_refresh,
        )

    return partial(
        update_forecast_cache_latest_aladin_temperature,
        cache_path,
        now=now,
        latitude=latitude,
        longitude=longitude,
        verify_ssl=verify_ssl,
        force_refresh=force_refresh,
    )


def ecmwf_meteogram_cache_update_job(
    cache_path: str | Path,
    *,
    station_id: str,
    force_refresh: bool = False,
) -> Callable[[], dict[str, Any]]:
    """Return the executor job for a latest ECMWF 10-day meteogram refresh."""
    return partial(
        update_forecast_cache_latest_ecmwf_meteogram,
        cache_path,
        station_id=station_id,
        force_refresh=force_refresh,
    )
