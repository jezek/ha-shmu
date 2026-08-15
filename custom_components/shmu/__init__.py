from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
from types import MappingProxyType
from datetime import datetime, timedelta, timezone
from .cache_paths import (
    ecmwf_meteogram_cache_path_for_entry,
    forecast_cache_path_for_subentry,
    forecast_cache_path_for_entry,
    migrate_legacy_ecmwf_meteogram_cache,
    seed_subentry_cache_from_legacy,
)
from .const import CONF_FORECAST_SOURCE, DOMAIN
from .api import SHMUAPI
from .forecast import ForecastCache
from .forecast_jobs import (
    ecmwf_meteogram_cache_update_job,
    forecast_cache_update_job,
    leading_day_aladin_fallback_job,
)
from .registry_migration import async_migrate_legacy_ecmwf_registry
from .runtime_sources import RuntimeSource, runtime_sources
from .subentry_migration import (
    MODEL_ALADIN,
    MODEL_ECMWF,
    SUBENTRY_LIVE_STATION,
    legacy_parent_data,
    legacy_subentry_data,
)
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate one coupled legacy source into a location and subentries."""
    if config_entry.version >= 2:
        return True

    existing_unique_ids = {
        child.unique_id for child in config_entry.subentries.values()
    }
    for item in legacy_subentry_data(dict(config_entry.data)):
        if item["unique_id"] in existing_unique_ids:
            continue
        child = config_entries.ConfigSubentry(
            data=MappingProxyType(item["data"]),
            subentry_type=item["subentry_type"],
            title=item["title"],
            unique_id=item["unique_id"],
        )
        hass.config_entries.async_add_subentry(config_entry, child)
        existing_unique_ids.add(item["unique_id"])

    parent_data = legacy_parent_data(dict(config_entry.data))
    hass.config_entries.async_update_entry(
        config_entry,
        data=parent_data,
        title=parent_data["location_name"],
        version=2,
        minor_version=0,
    )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SHMU integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    await async_migrate_legacy_ecmwf_registry(hass, entry.entry_id)
    await hass.async_add_executor_job(
        migrate_legacy_ecmwf_meteogram_cache,
        hass,
        entry,
    )

    coordinators = await async_create_source_coordinators(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"coordinators": coordinators}
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

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: RuntimeSource | None = None,
    ):
        """Initialize the coordinator."""
        self._hass = hass
        self._entry = entry
        self.source = source
        self._station_id = (
            source.source_id
            if source and source.source_type == SUBENTRY_LIVE_STATION
            else entry.data.get("station_id", "11813")
        )
        self._meteogram_id = (
            source.source_id
            if source and source.model in {MODEL_ALADIN, MODEL_ECMWF}
            else entry.data.get("meteogram_id", "none")
        )
        self._verify_ssl = entry.options.get(
            "verify_ssl", entry.data.get("verify_ssl", True)
        )
        self._api = (
            SHMUAPI(self._station_id, self._verify_ssl)
            if source is None or source.source_type == SUBENTRY_LIVE_STATION
            else None
        )
        self.forecast_rows = []
        self.forecast_historical_temperatures = {}
        self.forecast_history_info = {}
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
            name=(f"{DOMAIN}_{source.subentry_id}" if source else DOMAIN),
            update_interval=timedelta(seconds=entry.data.get("scan_interval", 300)),
        )

    async def _async_update_data(self):
        """Fetch data from SHMU API."""
        try:
            data = {}
            if self._api is not None:
                session = async_get_clientsession(self._hass)
                try:
                    data = await self._api.fetch_data(session)
                except Exception as err:
                    previous_data = getattr(self, "data", None)
                    if not previous_data:
                        raise
                    _LOGGER.warning(
                        "Unable to refresh SHMU current observations; preserving "
                        "the last valid station data: %s",
                        err,
                    )
                    data = previous_data
            source = getattr(self, "source", None)
            if source is None or source.model == MODEL_ALADIN:
                await self._async_refresh_forecast_cache()
            if source is None or source.model == MODEL_ECMWF:
                await self._async_refresh_ecmwf_meteogram_cache()
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with SHMU API: {err}")

    async def _async_refresh_forecast_cache(self, *, force_refresh: bool = False):
        """Refresh the forecast cache from helper source or native ALADIN data."""
        source = self._entry.options.get(
            CONF_FORECAST_SOURCE,
            self._entry.data.get(CONF_FORECAST_SOURCE),
        )

        cache_path = self._forecast_cache_path(MODEL_ALADIN)
        update_job = forecast_cache_update_job(
            cache_path,
            source=source,
            now=datetime.now(timezone.utc),
            latitude=self._hass.config.latitude,
            longitude=self._hass.config.longitude,
            verify_ssl=self._verify_ssl,
            force_refresh=force_refresh,
        )

        try:
            result = await self._hass.async_add_executor_job(update_job)
            self.forecast_rows = await self._hass.async_add_executor_job(
                ForecastCache(cache_path).load
            )
            self.forecast_cache_info = result["info"]
            await self._async_refresh_forecast_history()
        except Exception as err:
            _LOGGER.warning("Unable to refresh SHMU forecast cache: %s", err)
            return None

        if result["changed"]:
            _LOGGER.debug("Refreshed SHMU forecast cache: %s", result["info"])
        return result

    async def _async_refresh_forecast_history(self) -> None:
        """Load only history needed to complete the leading forecast boundary."""
        self.forecast_historical_temperatures = {}
        self.forecast_history_info = {}
        if not self.forecast_rows:
            return
        first_valid_time = min(row.valid_time for row in self.forecast_rows)
        now = datetime.now(timezone.utc)
        if first_valid_time > now or first_valid_time.hour == 0:
            return
        day_start = first_valid_time.replace(hour=0, minute=0, second=0, microsecond=0)
        if self._api is not None:
            session = async_get_clientsession(self._hass)
            try:
                self.forecast_historical_temperatures = (
                    await self._api.fetch_temperature_history(
                        session,
                        day_start,
                        first_valid_time,
                    )
                )
                self.forecast_history_info = {
                    "source": "observed_station_history",
                    "hour_count": len(self.forecast_historical_temperatures),
                }
                return
            except Exception as err:
                _LOGGER.warning("Unable to complete leading SHMU forecast day: %s", err)

        source = self._entry.options.get(
            CONF_FORECAST_SOURCE,
            self._entry.data.get(CONF_FORECAST_SOURCE),
        )
        if source:
            return
        try:
            result = await self._hass.async_add_executor_job(
                leading_day_aladin_fallback_job(
                    model_run_time=first_valid_time,
                    latitude=self._hass.config.latitude,
                    longitude=self._hass.config.longitude,
                    verify_ssl=self._verify_ssl,
                )
            )
            self.forecast_historical_temperatures = result["temperatures"]
            self.forecast_history_info = result["info"]
            _LOGGER.debug(
                "Completed leading SHMU forecast day from %s",
                self.forecast_history_info.get("source_run_id"),
            )
        except Exception as fallback_err:
            _LOGGER.warning(
                "Unable to use ALADIN leading-day fallback: %s", fallback_err
            )

    async def _async_refresh_ecmwf_meteogram_cache(self, station_id: str | None = None):
        """Refresh the separate ECMWF 10-day meteogram cache on explicit request."""
        selected_station_id = station_id or self._default_meteogram_station_id()
        cache_path = self._forecast_cache_path(MODEL_ECMWF)
        update_job = ecmwf_meteogram_cache_update_job(
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
            _LOGGER.warning("Unable to refresh SHMU ECMWF 10-day meteogram cache: %s", err)
            return None

        if result["changed"]:
            _LOGGER.debug("Refreshed SHMU ECMWF 10-day meteogram cache: %s", result["info"])
        return {**result, "station_id": selected_station_id}

    def _default_meteogram_station_id(self) -> str:
        """Return the configured ECMWF meteogram station id for manual ECMWF refresh."""
        if self._meteogram_id and self._meteogram_id != "none":
            return self._meteogram_id
        return self._station_id

    def _forecast_cache_path(self, model: str) -> str:
        """Return legacy or child-specific path for this coordinator."""
        source = getattr(self, "source", None)
        if source is not None:
            return forecast_cache_path_for_subentry(
                self._hass,
                self._entry,
                source.subentry_id,
                model,
            )
        if model == MODEL_ECMWF:
            return ecmwf_meteogram_cache_path_for_entry(self._hass, self._entry)
        return forecast_cache_path_for_entry(self._hass, self._entry)

    @callback
    def _handle_midnight_forecast_refresh(self, now) -> None:
        """Refresh forecast rows just after local midnight."""
        self._hass.async_create_task(self._async_midnight_forecast_refresh())

    async def _async_midnight_forecast_refresh(self) -> None:
        """Refresh only forecast cache and notify forecast entities."""
        source = getattr(self, "source", None)
        if source is None or source.model == MODEL_ALADIN:
            await self._async_refresh_forecast_cache()
        if source is None or source.model == MODEL_ECMWF:
            await self._async_refresh_ecmwf_meteogram_cache()
        self.async_update_listeners()


async def async_create_source_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator_factory=None,
) -> dict[str, SHMUDataUpdateCoordinator]:
    """Create and first-refresh one coordinator for every valid subentry.

    A source is independent from the other children of its location.  In
    particular, a temporarily unavailable live observation must not prevent
    forecast sources from being available.
    """
    factory = coordinator_factory or SHMUDataUpdateCoordinator
    coordinators: dict[str, SHMUDataUpdateCoordinator] = {}
    for source in runtime_sources(entry.subentries.values()):
        if source.preserve_legacy_ids and source.model is not None:
            await hass.async_add_executor_job(
                seed_subentry_cache_from_legacy,
                hass,
                entry,
                source.subentry_id,
                source.model,
            )
        coordinator = factory(hass, entry, source)
        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.warning(
                "Unable to initialize SHMU source %s (%s); continuing with "
                "the remaining sources: %s",
                source.subentry_id,
                source.source_id,
                err,
            )
            continue
        coordinators[source.subentry_id] = coordinator
    return coordinators
