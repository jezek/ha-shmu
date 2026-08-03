"""SHMU manual refresh buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity_helpers import ecmwf_meteogram_device_info, forecast_device_info


class SHMUForecastRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that refreshes the ALADIN forecast cache."""

    _attr_has_entity_name = True
    _attr_name = "Refresh forecast cache"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        """Initialize the ALADIN forecast refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.config_entry.entry_id}_refresh_forecast_cache"
        )
        self._attr_device_info = forecast_device_info(coordinator)

    async def async_press(self) -> None:
        """Refresh the ALADIN forecast cache."""
        result = await self.coordinator._async_refresh_forecast_cache(
            force_refresh=True
        )
        self.coordinator.async_update_listeners()
        if result is None:
            raise HomeAssistantError("SHMU forecast cache refresh failed")


class SHMUECMWFMeteogramRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that refreshes the ECMWF 10-day meteogram cache."""

    _attr_has_entity_name = True
    _attr_name = "Refresh ECMWF 10-day meteogram cache"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        """Initialize the ECMWF 10-day meteogram refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.config_entry.entry_id}_refresh_ecmwf_meteogram_cache"
        )
        self._attr_device_info = ecmwf_meteogram_device_info(coordinator)

    async def async_press(self) -> None:
        """Refresh the ECMWF 10-day meteogram cache."""
        result = await self.coordinator._async_refresh_ecmwf_meteogram_cache()
        self.coordinator.async_update_listeners()
        if result is None:
            raise HomeAssistantError("SHMU ECMWF 10-day meteogram cache refresh failed")


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up SHMU refresh buttons."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities(
        [
            SHMUForecastRefreshButton(coordinator),
            SHMUECMWFMeteogramRefreshButton(coordinator),
        ]
    )
