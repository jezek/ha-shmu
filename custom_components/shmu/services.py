"""Home Assistant services for cached SHMU forecast helper data."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ENTRY_ID,
    CONF_FORECAST_CACHE_PATH,
    DOMAIN,
    SERVICE_GET_FORECAST_COMPARISON,
    SERVICE_GET_FORECAST_SERIES,
)
from .forecast import (
    FORECAST_SERIES_FIELDS,
    ForecastCache,
    forecast_comparison,
    forecast_series,
)

_LOGGER = logging.getLogger(__name__)

CONF_END = "end"
CONF_FIELD = "field"
CONF_MAX_DISTANCE_MINUTES = "max_distance_minutes"
CONF_OBSERVATIONS = "observations"
CONF_START = "start"

_SERVICES_REGISTERED = "_services_registered"

_CACHE_SELECTOR_SCHEMA = {
    vol.Optional(CONF_ENTRY_ID): cv.string,
    vol.Optional(CONF_FORECAST_CACHE_PATH): cv.string,
}

GET_FORECAST_SERIES_SCHEMA = vol.Schema(
    {
        **_CACHE_SELECTOR_SCHEMA,
        vol.Required(CONF_FIELD): vol.In(sorted(FORECAST_SERIES_FIELDS)),
        vol.Optional(CONF_START): cv.string,
        vol.Optional(CONF_END): cv.string,
    }
)

GET_FORECAST_COMPARISON_SCHEMA = vol.Schema(
    {
        **_CACHE_SELECTOR_SCHEMA,
        vol.Required(CONF_FIELD): vol.In(sorted(FORECAST_SERIES_FIELDS)),
        vol.Required(CONF_OBSERVATIONS): cv.ensure_list,
        vol.Optional(CONF_MAX_DISTANCE_MINUTES, default=30.0): vol.Coerce(float),
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register SHMU forecast services once per Home Assistant instance."""
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get(_SERVICES_REGISTERED):
        return

    async def get_forecast_series(call: ServiceCall) -> dict[str, Any]:
        rows = await _async_load_rows(hass, call)
        try:
            series = forecast_series(
                rows,
                call.data[CONF_FIELD],
                start=_parse_service_datetime(call.data.get(CONF_START)),
                end=_parse_service_datetime(call.data.get(CONF_END)),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        return {"series": series, "count": len(series)}

    async def get_forecast_comparison(call: ServiceCall) -> dict[str, Any]:
        rows = await _async_load_rows(hass, call)
        try:
            comparison = forecast_comparison(
                rows,
                call.data[CONF_OBSERVATIONS],
                call.data[CONF_FIELD],
                max_distance_minutes=call.data[CONF_MAX_DISTANCE_MINUTES],
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        return {"comparison": comparison, "count": len(comparison)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FORECAST_SERIES,
        get_forecast_series,
        schema=GET_FORECAST_SERIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FORECAST_COMPARISON,
        get_forecast_comparison,
        schema=GET_FORECAST_COMPARISON_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.data[DOMAIN][_SERVICES_REGISTERED] = True


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister SHMU forecast services when the last entry unloads."""
    domain_data = hass.data.get(DOMAIN)
    if not domain_data or not domain_data.get(_SERVICES_REGISTERED):
        return
    entry_ids = [key for key in domain_data if key != _SERVICES_REGISTERED]
    if entry_ids:
        return

    hass.services.async_remove(DOMAIN, SERVICE_GET_FORECAST_SERIES)
    hass.services.async_remove(DOMAIN, SERVICE_GET_FORECAST_COMPARISON)
    domain_data.pop(_SERVICES_REGISTERED, None)


async def _async_load_rows(hass: HomeAssistant, call: ServiceCall):
    cache_path = _cache_path_for_call(hass, call)
    try:
        return await hass.async_add_executor_job(ForecastCache(cache_path).load)
    except FileNotFoundError as err:
        raise HomeAssistantError(f"SHMU forecast cache not found: {cache_path}") from err
    except ValueError as err:
        _LOGGER.warning("Invalid SHMU forecast cache: %s", err)
        raise HomeAssistantError(f"Invalid SHMU forecast cache: {err}") from err


def _cache_path_for_call(hass: HomeAssistant, call: ServiceCall) -> str:
    if cache_path := call.data.get(CONF_FORECAST_CACHE_PATH):
        return cache_path

    domain_data = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(CONF_ENTRY_ID)
    if entry_id:
        entry_data = domain_data.get(entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Unknown SHMU entry_id: {entry_id}")
        return _cache_path_for_entry_data(entry_data)

    entries = [data for key, data in domain_data.items() if key != _SERVICES_REGISTERED]
    if len(entries) != 1:
        raise HomeAssistantError(
            "Set entry_id or forecast_cache_path when multiple/no SHMU entries are loaded"
        )
    return _cache_path_for_entry_data(entries[0])


def _cache_path_for_entry_data(entry_data: dict[str, Any]) -> str:
    coordinator = entry_data["coordinator"]
    cache_path = coordinator.config_entry.options.get(
        CONF_FORECAST_CACHE_PATH,
        coordinator.config_entry.data.get(CONF_FORECAST_CACHE_PATH),
    )
    if not cache_path:
        raise HomeAssistantError("SHMU forecast_cache_path is not configured")
    return cache_path


def _parse_service_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"invalid datetime: {value}") from err
    if parsed.tzinfo is None:
        raise ValueError(f"datetime must include timezone: {value}")
    return parsed.astimezone(timezone.utc)
