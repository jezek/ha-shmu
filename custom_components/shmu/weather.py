"""SHMU weather forecast entity backed by normalized helper/cache rows."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timezone

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.helpers.sun import is_up
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity_helpers import (
    ecmwf_meteogram_device_info,
    entity_unique_id,
    forecast_device_info,
)
from .forecast import (
    ForecastCache,
    current_condition,
    rows_as_daily_forecast,
    rows_as_hourly_forecast,
)
from .subentry_migration import MODEL_ALADIN, MODEL_ECMWF

_LOGGER = logging.getLogger(__name__)


class SHMUWeather(CoordinatorEntity, WeatherEntity):
    """SHMU weather entity with cached hourly and daily forecasts."""

    _attr_has_entity_name = True
    _attr_name = "Forecast"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )
    _attr_native_temperature_unit = "°C"
    _attr_native_pressure_unit = "hPa"
    _attr_native_visibility_unit = "m"
    _attr_native_wind_speed_unit = "m/s"
    _attr_native_precipitation_unit = "mm"

    def __init__(self, coordinator, cache_path: str | None):
        """Initialize the forecast weather entity."""
        super().__init__(coordinator)
        self._cache = ForecastCache(cache_path) if cache_path else None
        self._attr_unique_id = entity_unique_id(coordinator, "weather")
        self._attr_device_info = forecast_device_info(coordinator)

    @property
    def available(self) -> bool:
        """Return whether current observation data is available."""
        return self.coordinator.last_update_success

    @property
    def condition(self) -> str | None:
        """Return observed rain or the nearest fresh ALADIN condition."""
        return current_condition(
            self.coordinator.forecast_rows,
            datetime.now(timezone.utc),
            self.coordinator.data.get("zra_uhrn"),
            is_daytime_at=lambda valid_time: is_up(self.hass, valid_time),
        )

    @property
    def native_temperature(self):
        """Return current observed temperature."""
        return self.coordinator.data.get("t")

    @property
    def native_pressure(self):
        """Return current observed pressure."""
        return self.coordinator.data.get("tlak")

    @property
    def humidity(self):
        """Return current observed relative humidity."""
        return self.coordinator.data.get("vlh_rel")

    @property
    def native_wind_speed(self):
        """Return current observed wind speed."""
        return self.coordinator.data.get("vie_pr_rych")

    @property
    def native_wind_gust_speed(self):
        """Return the current observed one-minute maximum wind speed."""
        return self.coordinator.data.get("vie_max_rych")

    @property
    def wind_bearing(self):
        """Return current observed wind bearing."""
        return self.coordinator.data.get("vie_pr_smer")

    @property
    def native_visibility(self):
        """Return current observed meteorological optical range."""
        return self.coordinator.data.get("dohl")

    async def async_forecast_hourly(self):
        """Return cached hourly forecast rows."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_hourly_forecast(
            rows,
            is_daytime_at=lambda valid_time: is_up(self.hass, valid_time),
        )

    async def async_forecast_daily(self):
        """Return cached daily forecast aggregates."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_daily_forecast(
            rows,
            self.coordinator.forecast_historical_temperatures,
            datetime.now(timezone.utc),
        )

    def _load_rows(self):
        if self._cache is None:
            return []
        try:
            return self._cache.load()
        except FileNotFoundError:
            return []
        except ValueError as err:
            _LOGGER.warning("Invalid SHMU forecast cache: %s", err)
            return []


class SHMUECMWFMeteogramWeather(CoordinatorEntity, WeatherEntity):
    """SHMU ECMWF 10-day meteogram weather entity backed by its separate cache."""

    _attr_has_entity_name = True
    _attr_name = "ECMWF 10-day meteogram"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )
    _attr_native_temperature_unit = "°C"
    _attr_native_pressure_unit = "hPa"
    _attr_native_visibility_unit = "m"
    _attr_native_wind_speed_unit = "m/s"
    _attr_native_precipitation_unit = "mm"

    def __init__(self, coordinator, cache_path: str):
        """Initialize the ECMWF 10-day meteogram forecast weather entity."""
        super().__init__(coordinator)
        self._cache_path = cache_path
        self._cache = ForecastCache(cache_path)
        self._attr_unique_id = entity_unique_id(
            coordinator, "ecmwf_meteogram_weather"
        )
        self._attr_device_info = ecmwf_meteogram_device_info(coordinator)

    @property
    def available(self) -> bool:
        """Return whether an ECMWF 10-day meteogram cache is available."""
        return bool(getattr(self.coordinator, "ecmwf_forecast_rows", [])) or Path(
            self._cache_path
        ).exists()

    @property
    def condition(self) -> str | None:
        """Return observed rain or the nearest fresh ECMWF condition."""
        return current_condition(
            self.coordinator.ecmwf_forecast_rows,
            datetime.now(timezone.utc),
            self.coordinator.data.get("zra_uhrn"),
            is_daytime_at=lambda valid_time: is_up(self.hass, valid_time),
        )

    @property
    def native_temperature(self):
        """Return the current observed station temperature when available."""
        return self.coordinator.data.get("t")

    @property
    def native_pressure(self):
        """Return current observed pressure."""
        return self.coordinator.data.get("tlak")

    @property
    def humidity(self):
        """Return current observed relative humidity."""
        return self.coordinator.data.get("vlh_rel")

    @property
    def native_wind_speed(self):
        """Return current observed wind speed."""
        return self.coordinator.data.get("vie_pr_rych")

    @property
    def native_wind_gust_speed(self):
        """Return the current observed one-minute maximum wind speed."""
        return self.coordinator.data.get("vie_max_rych")

    @property
    def wind_bearing(self):
        """Return current observed wind bearing."""
        return self.coordinator.data.get("vie_pr_smer")

    @property
    def native_visibility(self):
        """Return current observed meteorological optical range."""
        return self.coordinator.data.get("dohl")

    async def async_forecast_hourly(self):
        """Return cached ECMWF 10-day meteogram hourly forecast rows."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_hourly_forecast(
            rows,
            is_daytime_at=lambda valid_time: is_up(self.hass, valid_time),
        )

    async def async_forecast_daily(self):
        """Return cached ECMWF 10-day meteogram daily forecast aggregates."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_daily_forecast(rows, require_hourly_coverage=False)

    def _load_rows(self):
        try:
            return self._cache.load()
        except FileNotFoundError:
            return []
        except ValueError as err:
            _LOGGER.warning("Invalid SHMU ECMWF 10-day meteogram cache: %s", err)
            return []


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the SHMU weather entities."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    for subentry_id, coordinator in entry_data["coordinators"].items():
        if coordinator.source.model == MODEL_ALADIN:
            entities = [
                SHMUWeather(
                    coordinator,
                    coordinator._forecast_cache_path(MODEL_ALADIN),
                )
            ]
        elif coordinator.source.model == MODEL_ECMWF:
            entities = [
                SHMUECMWFMeteogramWeather(
                    coordinator,
                    coordinator._forecast_cache_path(MODEL_ECMWF),
                )
            ]
        else:
            continue
        async_add_entities(entities, config_subentry_id=subentry_id)
