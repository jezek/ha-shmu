"""Runtime helpers for refreshing the SHMU forecast cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .forecast import ForecastCache, parse_helper_forecast


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
