from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from datetime import datetime, timedelta
from .cache_paths import forecast_cache_path_for_entry
from .const import DOMAIN
from .entity_helpers import (
    aladin_meteogram_page_url,
    ecmwf_meteogram_device_info,
    entity_unique_id,
    forecast_device_info,
    station_device_info,
)
from .forecast import forecast_summary
from .subentry_migration import (
    MODEL_ALADIN,
    MODEL_ECMWF,
    SUBENTRY_LIVE_STATION,
)
from homeassistant.util.dt import now

class SHMUSensor(CoordinatorEntity, SensorEntity):
    """Representation of a SHMU sensor."""

    def __init__(
        self,
        coordinator,
        sensor_key: str,
        name: str,
        unit: str,
        device_class: SensorDeviceClass = None,
        icon: str = None,
        state_class: SensorStateClass = None,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._name = name
        self._unit = unit
        self._device_class = device_class
        self._icon = icon
        self._state_class = state_class
        self._attr_unique_id = entity_unique_id(coordinator, sensor_key)

        self._attr_device_info = station_device_info(coordinator)

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._sensor_key)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement as a string."""
        return self._unit

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return self._device_class

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class."""
        return self._state_class

    @property
    def icon(self) -> str:
        """Return the icon."""
        return self._icon


class SHMUMeteogramSensor(CoordinatorEntity, SensorEntity):
    """Representation of a SHMU meteogram URL sensor."""

    def __init__(self, coordinator, meteogram_id=None):
        """Initialize the meteogram URL sensor."""
        super().__init__(coordinator)
        self._attr_name = "Meteogram URL"
        self._attr_unique_id = entity_unique_id(
            coordinator,
            "meteogram_url",
            legacy_unique_id=(
                f"{DOMAIN}_meteogram_url_{coordinator.config_entry.entry_id}"
            ),
        )
        self._attr_icon = "mdi:image"
        self._meteogram_id = meteogram_id or "32737"  # Default meteogram ID

        source = getattr(coordinator, "source", None)
        self._attr_device_info = (
            forecast_device_info(coordinator)
            if source and source.model == MODEL_ALADIN
            else station_device_info(coordinator)
        )

    def _generate_meteogram_url(self):
        """Generate the meteogram URL based on current time."""
        now = datetime.now()
        if now.hour < 6:
            date = (now - timedelta(days=1)).strftime("%Y%m%d")
            time = "1600"
        elif now.hour < 12:
            date = now.strftime("%Y%m%d")
            time = "0000"
        elif now.hour < 17:
            date = now.strftime("%Y%m%d")
            time = "0600"
        else:
            date = now.strftime("%Y%m%d")
            time = "1200"
            
        if now.hour < 10:
            date10 = (now - timedelta(days=1)).strftime("%Y%m%d")
            time10 = "1200"
        elif now.hour < 22:
            date10 = now.strftime("%Y%m%d")
            time10 = "0000"
        else:
            date10 = now.strftime("%Y%m%d")
            time10 = "1200"
            
        return (
            f"https://www.shmu.sk/data/datanwp/v2/meteogram/al-meteogram_{self._meteogram_id}-{date}-{time}-nwp-.png",
            f"https://www.shmu.sk/data/datanwp/v2/ecmgram/al-ecmgram_{self._meteogram_id}-{date10}-{time10}-nwp-.png"
            )
    @property
    def native_value(self):
        """Return the meteogram URL."""
        return aladin_meteogram_page_url(self._meteogram_id)

    @property
    def extra_state_attributes(self):
        """Return the attributes for the meteogram URL."""
        meteo3, meteo10 = self._generate_meteogram_url()
        return {"meteogram_3d_url": meteo3, "meteogram_10d_url": meteo10}


class SHMUForecastSummarySensor(CoordinatorEntity, SensorEntity):
    """Compact forecast summary sensor backed by the helper/cache boundary."""

    def __init__(
        self,
        coordinator,
        cache_path: str,
        summary_key: str,
        name: str,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
        icon: str | None = None,
    ):
        """Initialize the forecast summary sensor."""
        super().__init__(coordinator)
        self._summary_key = summary_key
        self._attr_name = name
        self._attr_unique_id = entity_unique_id(coordinator, summary_key)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

        source = getattr(coordinator, "source", None)
        self._attr_device_info = (
            ecmwf_meteogram_device_info(coordinator)
            if source and source.model == MODEL_ECMWF
            else forecast_device_info(coordinator)
        )

    @property
    def native_value(self):
        """Return the selected forecast summary value."""
        source = getattr(self.coordinator, "source", None)
        rows = (
            self.coordinator.ecmwf_forecast_rows
            if source and source.model == MODEL_ECMWF
            else self.coordinator.forecast_rows
        )
        if not rows:
            return None
        return forecast_summary(rows, now()).get(self._summary_key)


class SHMUForecastCacheInfoSensor(CoordinatorEntity, SensorEntity):
    """Forecast cache freshness sensor backed by helper/cache metadata."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        cache_path: str,
        info_key: str,
        name: str,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
    ):
        """Initialize the forecast cache freshness sensor."""
        super().__init__(coordinator)
        self._info_key = info_key
        self._attr_name = name
        self._attr_unique_id = entity_unique_id(coordinator, info_key)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon

        self._attr_device_info = forecast_device_info(coordinator)

    @property
    def native_value(self):
        """Return the selected cache freshness value."""
        info = self.coordinator.forecast_cache_info
        if not info:
            return None
        value = info.get(self._info_key)
        if self._info_key in {
            "file_modified_time",
            "model_run_time",
            "oldest_valid_time",
            "newest_valid_time",
        } and isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if self._info_key == "age_seconds" and value is not None:
            modified_time = info.get("file_modified_time")
            if isinstance(modified_time, str):
                modified = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
                return round(max(0.0, (now() - modified).total_seconds()))
            return round(value)
        return value


class SHMUForecastHistoryInfoSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing leading-day temperature provenance."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, info_key: str, name: str, icon: str):
        super().__init__(coordinator)
        self._info_key = info_key
        self._attr_name = name
        self._attr_unique_id = entity_unique_id(
            coordinator, f"forecast_history_{info_key}"
        )
        self._attr_icon = icon
        self._attr_device_info = forecast_device_info(coordinator)

    @property
    def native_value(self):
        """Return selected leading-day history metadata."""
        return self.coordinator.forecast_history_info.get(self._info_key)


class SHMUECMWFMeteogramCacheInfoSensor(CoordinatorEntity, SensorEntity):
    """ECMWF 10-day meteogram cache diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        info_key: str,
        name: str,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
    ):
        """Initialize an ECMWF meteogram cache diagnostic sensor."""
        super().__init__(coordinator)
        self._info_key = info_key
        self._attr_name = name
        self._attr_unique_id = entity_unique_id(
            coordinator, f"ecmwf_meteogram_{info_key}"
        )
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_device_info = ecmwf_meteogram_device_info(coordinator)

    @property
    def native_value(self):
        """Return selected ECMWF meteogram cache metadata."""
        info = self.coordinator.ecmwf_cache_info
        if not info:
            return None
        value = info.get(self._info_key)
        if self._info_key in {
            "downloaded_time",
            "model_run_time",
            "oldest_valid_time",
            "newest_valid_time",
        } and isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


def _build_sensors(hass, coordinator):
    """Build the compatible sensor set for one coordinator."""
    source = getattr(coordinator, "source", None)
    meteogram_id = (
        source.source_id
        if source and source.model in {MODEL_ALADIN, MODEL_ECMWF}
        else coordinator.config_entry.data.get("meteogram_id", "none")
    )
    sensors = [
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="t",
            name="Temperature",
            unit="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:thermometer",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="vlh_rel",
            name="Humidity",
            unit=PERCENTAGE,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:water-percent",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="tlak",
            name="Pressure",
            unit="hPa",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:gauge",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="vie_pr_rych",
            name="Wind Speed",
            unit="m/s",
            device_class=SensorDeviceClass.WIND_SPEED,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:weather-windy",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="vie_pr_smer",
            name="Wind Direction",
            unit="°",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:compass",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="sln_trv",
            name="Sun duration/min",
            unit="s",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:sun-clock",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="zglo",
            name="Global radiation",
            unit="W/m²",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:sun-wireless",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="zra_trv",
            name="Precipitation duration/min",
            unit="s",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:weather-rainy",
        ),
        SHMUSensor(
            coordinator=coordinator,
            sensor_key="zra_uhrn",
            name="Precipitation volume",
            unit="mm",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:cup-water",
        )]
    # Only add the meteogram sensor if meteogram_id is not "none"
    if meteogram_id != "none":
        sensors.append(SHMUMeteogramSensor(coordinator, meteogram_id))

    forecast_model = (
        MODEL_ECMWF if source and source.model == MODEL_ECMWF else MODEL_ALADIN
    )
    forecast_cache_path = (
        coordinator._forecast_cache_path(forecast_model)
        if source
        else forecast_cache_path_for_entry(hass, coordinator.config_entry)
    )
    sensors.extend(
        [
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "tomorrow_min_temperature",
                "Tomorrow minimum temperature",
                "°C",
                SensorDeviceClass.TEMPERATURE,
                "mdi:thermometer-chevron-down",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "tomorrow_max_temperature",
                "Tomorrow maximum temperature",
                "°C",
                SensorDeviceClass.TEMPERATURE,
                "mdi:thermometer-chevron-up",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "next_precipitation_time",
                "Next precipitation time",
                None,
                SensorDeviceClass.TIMESTAMP,
                "mdi:weather-rainy",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "next_precipitation_amount",
                "Next precipitation amount",
                "mm",
                None,
                "mdi:cup-water",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "strongest_gust_time",
                "Strongest gust time",
                None,
                SensorDeviceClass.TIMESTAMP,
                "mdi:weather-windy",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "strongest_gust_speed",
                "Strongest gust speed",
                "m/s",
                SensorDeviceClass.WIND_SPEED,
                "mdi:weather-windy",
            ),
            SHMUForecastSummarySensor(
                coordinator,
                forecast_cache_path,
                "next_clear_window_time",
                "Next clear window time",
                None,
                SensorDeviceClass.TIMESTAMP,
                "mdi:weather-sunny",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "file_modified_time",
                "Forecast cache modified time",
                None,
                SensorDeviceClass.TIMESTAMP,
                None,
                "mdi:file-clock",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "age_seconds",
                "Forecast cache age",
                "s",
                None,
                SensorStateClass.MEASUREMENT,
                "mdi:timer-sand",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "row_count",
                "Forecast cache row count",
                None,
                None,
                SensorStateClass.MEASUREMENT,
                "mdi:table-row",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "model_run_time",
                "Forecast model run time",
                None,
                SensorDeviceClass.TIMESTAMP,
                None,
                "mdi:clock-start",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "oldest_valid_time",
                "Forecast record from",
                None,
                SensorDeviceClass.TIMESTAMP,
                None,
                "mdi:clock-outline",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "newest_valid_time",
                "Forecast record to",
                None,
                SensorDeviceClass.TIMESTAMP,
                None,
                "mdi:clock-end",
            ),
            SHMUForecastCacheInfoSensor(
                coordinator,
                forecast_cache_path,
                "source_run_id",
                "Forecast source run",
                None,
                None,
                None,
                "mdi:identifier",
            ),
            SHMUForecastHistoryInfoSensor(
                coordinator,
                "source",
                "Forecast leading-day temperature source",
                "mdi:source-branch",
            ),
            SHMUForecastHistoryInfoSensor(
                coordinator,
                "source_run_id",
                "Forecast leading-day fallback run",
                "mdi:identifier",
            ),
        ]
    )
    sensors.extend(
        [
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "source_filename",
                "ECMWF meteogram source filename",
                icon="mdi:file-document-outline",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "downloaded_time",
                "ECMWF meteogram downloaded time",
                SensorDeviceClass.TIMESTAMP,
                icon="mdi:download",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "row_count",
                "ECMWF meteogram record count",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:table-row",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "oldest_valid_time",
                "ECMWF meteogram record from",
                SensorDeviceClass.TIMESTAMP,
                icon="mdi:clock-outline",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "newest_valid_time",
                "ECMWF meteogram record to",
                SensorDeviceClass.TIMESTAMP,
                icon="mdi:clock-end",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "model_run_time",
                "ECMWF meteogram model run time",
                SensorDeviceClass.TIMESTAMP,
                icon="mdi:clock-start",
            ),
            SHMUECMWFMeteogramCacheInfoSensor(
                coordinator,
                "source_run_id",
                "ECMWF meteogram source run",
                icon="mdi:identifier",
            ),
        ]
    )

    if source is None:
        return sensors
    if source.source_type == SUBENTRY_LIVE_STATION:
        return [sensor for sensor in sensors if type(sensor) is SHMUSensor]
    if source.model == MODEL_ALADIN:
        return [
            sensor
            for sensor in sensors
            if isinstance(
                sensor,
                (
                    SHMUMeteogramSensor,
                    SHMUForecastSummarySensor,
                    SHMUForecastCacheInfoSensor,
                    SHMUForecastHistoryInfoSensor,
                ),
            )
        ]
    if source.model == MODEL_ECMWF:
        return [
            sensor
            for sensor in sensors
            if isinstance(
                sensor,
                (SHMUForecastSummarySensor, SHMUECMWFMeteogramCacheInfoSensor),
            )
        ]
    return []


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up sensors under their independently configured sources."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    for subentry_id, coordinator in entry_data["coordinators"].items():
        sensors = _build_sensors(hass, coordinator)
        if sensors:
            async_add_entities(sensors, config_subentry_id=subentry_id)
