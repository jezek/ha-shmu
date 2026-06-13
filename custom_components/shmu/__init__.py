from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
from datetime import timedelta
from .cache_paths import forecast_cache_path_for_entry
from .const import CONF_FORECAST_SOURCE, DOMAIN
from .api import SHMUAPI
from .forecast_update import update_forecast_cache_source
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SHMU integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = SHMUDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}
    await async_setup_services(hass)

    # Forward setup to sensor and weather platforms.
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "weather"])

    return True
    
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, ["sensor", "weather"]):
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

    async def _async_refresh_forecast_cache(self) -> None:
        """Refresh the forecast cache from the configured helper source."""
        source = self._entry.options.get(
            CONF_FORECAST_SOURCE,
            self._entry.data.get(CONF_FORECAST_SOURCE),
        )
        if not source:
            return

        cache_path = forecast_cache_path_for_entry(self._hass, self._entry)
        try:
            result = await self._hass.async_add_executor_job(
                update_forecast_cache_source,
                cache_path,
                source,
            )
        except Exception as err:
            _LOGGER.warning("Unable to refresh SHMU forecast cache: %s", err)
            return

        if result["changed"]:
            _LOGGER.debug("Refreshed SHMU forecast cache: %s", result["info"])
