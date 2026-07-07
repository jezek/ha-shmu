from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
from datetime import datetime, timedelta, timezone
from .cache_paths import ecmwf_epsgram_cache_path_for_entry, forecast_cache_path_for_entry
from .const import CONF_FORECAST_SOURCE, DOMAIN
from .api import SHMUAPI
from .forecast import ForecastCache
from .forecast_jobs import ecmwf_epsgram_cache_update_job, forecast_cache_update_job
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SHMU integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = SHMUDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}
    await async_setup_services(hass)

    # Forward setup to entity platforms.
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "weather", "button"])

    return True
    
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "weather", "button"]
    ):
        hass.data[DOMAIN].pop(entry.entry_id)
        await async_unload_services(hass)
    return unload_ok

class SHMUDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SHMU data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        self._hass = hass
        self._entry = entry
        self._station_id = entry.data.get("station_id", "11813")
        self._meteogram_id = entry.data.get("meteogram_id", "none")
        self._verify_ssl = entry.data.get("verify_ssl", True)
        self._api = SHMUAPI(self._station_id, self._verify_ssl)
        self.forecast_rows = []
        self.forecast_cache_info = {}
        self.ecmwf_forecast_rows = []
        self.ecmwf_cache_info = {}
        entry.async_on_unload(
            async_track_time_change(
                hass,
                self._handle_midnight_forecast_refresh,
                hour=0,
                minute=1,
                second=0,
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.data.get("scan_interval", 300)),
        )

    async def _async_update_data(self):
        """Fetch data from SHMU API."""
        try:
            session = async_get_clientsession(self._hass)
            data = await self._api.fetch_data(session)
            await self._async_refresh_forecast_cache()
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with SHMU API: {err}")

    async def _async_refresh_forecast_cache(self):
        """Refresh the forecast cache from helper source or native ALADIN data."""
        source = self._entry.options.get(
            CONF_FORECAST_SOURCE,
            self._entry.data.get(CONF_FORECAST_SOURCE),
        )

        cache_path = forecast_cache_path_for_entry(self._hass, self._entry)
        update_job = forecast_cache_update_job(
            cache_path,
            source=source,
            now=datetime.now(timezone.utc),
            latitude=self._hass.config.latitude,
            longitude=self._hass.config.longitude,
            verify_ssl=self._verify_ssl,
        )

        try:
            result = await self._hass.async_add_executor_job(update_job)
            self.forecast_rows = await self._hass.async_add_executor_job(
                ForecastCache(cache_path).load
            )
            self.forecast_cache_info = result["info"]
        except Exception as err:
            _LOGGER.warning("Unable to refresh SHMU forecast cache: %s", err)
            return None

        if result["changed"]:
            _LOGGER.debug("Refreshed SHMU forecast cache: %s", result["info"])
        return result

    async def _async_refresh_ecmwf_epsgram_cache(self, station_id: str | None = None):
        """Refresh the separate ECMWF EPSGRAM cache on explicit request."""
        selected_station_id = station_id or self._default_epsgram_station_id()
        cache_path = ecmwf_epsgram_cache_path_for_entry(self._hass, self._entry)
        update_job = ecmwf_epsgram_cache_update_job(
            cache_path,
            station_id=selected_station_id,
        )

        try:
            result = await self._hass.async_add_executor_job(update_job)
            self.ecmwf_forecast_rows = await self._hass.async_add_executor_job(
                ForecastCache(cache_path).load
            )
            self.ecmwf_cache_info = result["info"]
        except Exception as err:
            _LOGGER.warning("Unable to refresh SHMU ECMWF EPSGRAM cache: %s", err)
            return None

        if result["changed"]:
            _LOGGER.debug("Refreshed SHMU ECMWF EPSGRAM cache: %s", result["info"])
        return {**result, "station_id": selected_station_id}

    def _default_epsgram_station_id(self) -> str:
        """Return the configured EPSGRAM-like station id for manual ECMWF refresh."""
        if self._meteogram_id and self._meteogram_id != "none":
            return self._meteogram_id
        return self._station_id

    @callback
    def _handle_midnight_forecast_refresh(self, now) -> None:
        """Refresh forecast rows just after local midnight."""
        self._hass.async_create_task(self._async_midnight_forecast_refresh())

    async def _async_midnight_forecast_refresh(self) -> None:
        """Refresh only forecast cache and notify forecast entities."""
        await self._async_refresh_forecast_cache()
        self.async_update_listeners()
