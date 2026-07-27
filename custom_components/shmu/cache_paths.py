"""Forecast cache path helpers for SHMU config entries."""

from __future__ import annotations

from typing import Any

from .const import CONF_FORECAST_CACHE_PATH

FORECAST_CACHE_DIR = "shmu"
FORECAST_CACHE_FILENAME_TEMPLATE = "forecast-cache-{entry_id}.json"
ECMWF_METEOGRAM_CACHE_FILENAME_TEMPLATE = "ecmwf-meteogram-cache-{entry_id}.json"


def forecast_cache_path_for_entry(hass: Any, config_entry: Any) -> str:
    """Return the configured forecast cache path or the integration-owned default."""
    configured_path = config_entry.options.get(
        CONF_FORECAST_CACHE_PATH,
        config_entry.data.get(CONF_FORECAST_CACHE_PATH),
    )
    if configured_path:
        return configured_path

    return hass.config.path(
        FORECAST_CACHE_DIR,
        FORECAST_CACHE_FILENAME_TEMPLATE.format(entry_id=config_entry.entry_id),
    )


def ecmwf_meteogram_cache_path_for_entry(hass: Any, config_entry: Any) -> str:
    """Return the integration-owned ECMWF 10-day meteogram cache path for an entry."""
    return hass.config.path(
        FORECAST_CACHE_DIR,
        ECMWF_METEOGRAM_CACHE_FILENAME_TEMPLATE.format(entry_id=config_entry.entry_id),
    )
