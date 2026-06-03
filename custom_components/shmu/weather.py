"""SHMU weather forecast entity backed by normalized helper/cache rows."""

from __future__ import annotations

import logging

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FORECAST_CACHE_PATH, DOMAIN
from .forecast import ForecastCache, rows_as_daily_forecast, rows_as_hourly_forecast

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
    _attr_native_wind_speed_unit = "m/s"
    _attr_native_precipitation_unit = "mm"

    def __init__(self, coordinator, cache_path: str | None):
        """Initialize the forecast weather entity."""
        super().__init__(coordinator)
        station_id = coordinator.config_entry.data["station_id"]
        self._cache = ForecastCache(cache_path) if cache_path else None
        self._attr_unique_id = f"{DOMAIN}_{coordinator.config_entry.entry_id}_weather"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=f"SHMU Station {station_id}",
            manufacturer="Slovenský hydrometeorologický ústav",
            model="Weather Station",
            sw_version="1.0",
        )

    @property
    def available(self) -> bool:
        """Return whether current observation data is available."""
        return self.coordinator.last_update_success

    @property
    def condition(self) -> str | None:
        """Return a conservative current condition from observation rain data."""
        precipitation = self.coordinator.data.get("zra_uhrn")
        if precipitation is not None and float(precipitation) > 0:
            return "rainy"
        return "cloudy"

    @property
    def native_temperature(self):
        """Return current observed temperature."""
        return self.coordinator.data.get("t")

    @property
    def native_pressure(self):
        """Return current observed pressure."""
        return self.coordinator.data.get("tlak")

    @property
    def native_wind_speed(self):
        """Return current observed wind speed."""
        return self.coordinator.data.get("vie_pr_rych")

    @property
    def wind_bearing(self):
        """Return current observed wind bearing."""
        return self.coordinator.data.get("vie_pr_smer")

    async def async_forecast_hourly(self):
        """Return cached hourly forecast rows."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_hourly_forecast(rows)

    async def async_forecast_daily(self):
        """Return cached daily forecast aggregates."""
        rows = await self.hass.async_add_executor_job(self._load_rows)
        return rows_as_daily_forecast(rows)

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


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the SHMU weather entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    cache_path = config_entry.data.get(CONF_FORECAST_CACHE_PATH)
    async_add_entities([SHMUWeather(coordinator, cache_path)])
