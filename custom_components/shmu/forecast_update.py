"""Runtime helpers for refreshing the SHMU forecast cache."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .aladin import (
    download_grib_leads,
    latest_model_run_time,
    opener_for_verify_ssl,
    run_id,
    run_url,
    temperature_payload_from_grib_leads,
)
from .forecast import ForecastCache, parse_helper_forecast

DEFAULT_ALADIN_TEMPERATURE_LEAD_HOURS = tuple(range(49))


def read_helper_payload(source: str) -> dict[str, Any]:
    """Read helper-compatible JSON from a local file or HTTP(S) URL."""
    if urlparse(source).scheme in {"http", "https"}:
        request = Request(source, headers={"User-Agent": "ha-shmu-forecast-cache/1.0"})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    else:
        with Path(source).open(encoding="utf-8") as handle:
            payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("helper payload must be a JSON object")
    return payload


def update_forecast_cache_source(
    cache_path: str | Path,
    source: str,
) -> dict[str, Any]:
    """Read a helper payload from source and update the forecast cache."""
    return update_forecast_cache_payload(cache_path, read_helper_payload(source))


def update_forecast_cache_aladin_temperature(
    cache_path: str | Path,
    *,
    model_run_time: datetime,
    latitude: float,
    longitude: float,
    lead_hours: Iterable[int] | None = None,
    timeout: int = 30,
    verify_ssl: bool = True,
    opener=None,
) -> dict[str, Any]:
    """Download ALADIN GRIB leads and update the temperature forecast cache."""
    source_run_id = run_id(model_run_time)
    cache = ForecastCache(cache_path)
    try:
        current_info = cache.info()
    except (FileNotFoundError, ValueError):
        current_info = None

    if current_info and current_info.get("source_run_id") == source_run_id:
        return {"changed": False, "info": current_info}

    selected_opener = opener if opener is not None else opener_for_verify_ssl(verify_ssl)
    payload = temperature_payload_from_grib_leads(
        model_run_time=model_run_time,
        source_url=run_url(model_run_time),
        source_run_id=source_run_id,
        latitude=latitude,
        longitude=longitude,
        grib_leads=download_grib_leads(
            model_run_time,
            DEFAULT_ALADIN_TEMPERATURE_LEAD_HOURS
            if lead_hours is None
            else lead_hours,
            timeout=timeout,
            opener=selected_opener,
        ),
    )
    return update_forecast_cache_payload(cache_path, payload)


def update_forecast_cache_latest_aladin_temperature(
    cache_path: str | Path,
    *,
    now: datetime,
    latitude: float,
    longitude: float,
    lead_hours: Iterable[int] | None = None,
    timeout: int = 30,
    verify_ssl: bool = True,
    opener=None,
) -> dict[str, Any]:
    """Update the cache from the latest ALADIN run that should be available."""
    return update_forecast_cache_aladin_temperature(
        cache_path,
        model_run_time=latest_model_run_time(now),
        latitude=latitude,
        longitude=longitude,
        lead_hours=lead_hours,
        timeout=timeout,
        verify_ssl=verify_ssl,
        opener=opener,
    )


def update_forecast_cache_payload(
    cache_path: str | Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate and write a helper payload unless the cached run is unchanged."""
    parse_helper_forecast(payload)
    incoming_run_id = str(payload["source_run_id"])
    cache = ForecastCache(cache_path)

    try:
        current_info = cache.info()
    except (FileNotFoundError, ValueError):
        current_info = None

    if current_info and current_info.get("source_run_id") == incoming_run_id:
        return {"changed": False, "info": current_info}

    cache.save_payload(payload)
    return {"changed": True, "info": cache.info()}
