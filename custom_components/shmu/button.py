"""SHMU manual refresh buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity_helpers import ecmwf_epsgram_device_info, forecast_device_info


class SHMUForecastRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that refreshes the ALADIN forecast cache."""

    _attr_has_entity_name = True
    _attr_name = "Refresh forecast cache"

    def __init__(self, coordinator):
        """Initialize the ALADIN forecast refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.config_entry.entry_id}_refresh_forecast_cache"
        )
        self._attr_device_info = forecast_device_info(coordinator)

    async def async_press(self) -> None:
        """Refresh the ALADIN forecast cache."""
        result = await self.coordinator._async_refresh_forecast_cache()
        self.coordinator.async_update_listeners()
        if result is None:
            raise HomeAssistantError("SHMU forecast cache refresh failed")


class SHMUECMWFEPSGRAMRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that refreshes the ECMWF EPSGRAM cache."""

    _attr_has_entity_name = True
    _attr_name = "Refresh ECMWF EPSGRAM cache"

    def __init__(self, coordinator):
        """Initialize the ECMWF EPSGRAM refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.config_entry.entry_id}_refresh_ecmwf_epsgram_cache"
        )
        self._attr_device_info = ecmwf_epsgram_device_info(coordinator)

    async def async_press(self) -> None:
        """Refresh the ECMWF EPSGRAM cache."""
        result = await self.coordinator._async_refresh_ecmwf_epsgram_cache()
        self.coordinator.async_update_listeners()
        if result is None:
            raise HomeAssistantError("SHMU ECMWF EPSGRAM cache refresh failed")


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up SHMU refresh buttons."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities(
        [
            SHMUForecastRefreshButton(coordinator),
            SHMUECMWFEPSGRAMRefreshButton(coordinator),
        ]
    )
