"""Runtime helpers for refreshing the SHMU forecast cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .forecast import ForecastCache, parse_helper_forecast


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
