"""Runtime helpers for refreshing the SHMU forecast cache."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .aladin import (
    download_grib_leads,
    forecast_payload_from_grib_leads,
    latest_model_run_time,
    opener_for_verify_ssl,
    run_id,
    run_url,
)
from .epsgram import ecmwf_helper_payload, latest_station_product, product_json_url
from .forecast import ForecastCache, parse_helper_forecast

DEFAULT_ALADIN_TEMPERATURE_LEAD_HOURS = tuple(range(79))
FORECAST_CACHE_USER_AGENT = "ha-shmu-forecast-cache/1.0"
SHMU_EPSGRAM_STATION_PRODUCTS_URL = (
    "https://www.shmu.sk/api/v1/nwp/getstationproducts?station={station_id}"
)


def read_helper_payload(source: str) -> dict[str, Any]:
    """Read helper-compatible JSON from a local file or HTTP(S) URL."""
    if urlparse(source).scheme in {"http", "https"}:
        payload = read_json_url(source)
    else:
        with Path(source).open(encoding="utf-8") as handle:
            payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("helper payload must be a JSON object")
    return payload


def read_json_url(source: str, *, timeout: int = 30, opener=None) -> dict[str, Any]:
    """Read a JSON object from an HTTP(S) URL."""
    request = Request(source, headers={"User-Agent": FORECAST_CACHE_USER_AGENT})
    selected_opener = opener if opener is not None else urlopen
    with selected_opener(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("JSON URL payload must be an object")
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
    payload = forecast_payload_from_grib_leads(
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
            stop_at_first_not_found=lead_hours is None,
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
    """Update from the newest published ALADIN run, falling back on HTTP 404."""
    candidate_before = now
    for _ in range(5):
        model_run_time = latest_model_run_time(
            candidate_before,
            availability_lag=timedelta(0),
        )
        try:
            return update_forecast_cache_aladin_temperature(
                cache_path,
                model_run_time=model_run_time,
                latitude=latitude,
                longitude=longitude,
                lead_hours=lead_hours,
                timeout=timeout,
                verify_ssl=verify_ssl,
                opener=opener,
            )
        except HTTPError as err:
            if err.code != 404:
                raise
            err.close()
            candidate_before = model_run_time - timedelta(seconds=1)

    raise FileNotFoundError("no published ALADIN run found in the latest candidates")


def update_forecast_cache_latest_ecmwf_epsgram(
    cache_path: str | Path,
    *,
    station_id: str,
    timeout: int = 30,
    opener=None,
) -> dict[str, Any]:
    """Update the cache from the latest interactive ECMWF EPSGRAM product."""
    station_products_url = SHMU_EPSGRAM_STATION_PRODUCTS_URL.format(station_id=station_id)
    station_products = read_json_url(station_products_url, timeout=timeout, opener=opener)
    product = latest_station_product(station_products, "ecmwf")
    file_link = product.get("file_link")
    if not isinstance(file_link, str):
        raise ValueError("ECMWF station product must contain file_link")

    source_url = product_json_url(file_link)
    epsgram_payload = read_json_url(source_url, timeout=timeout, opener=opener)
    return update_forecast_cache_payload(
        cache_path,
        ecmwf_helper_payload(epsgram_payload, source_url),
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
