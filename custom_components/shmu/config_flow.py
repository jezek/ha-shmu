"""Configuration flow for SHMU."""

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import DOMAIN
from .location_catalog import (
    LocationOption,
    async_fetch_location_catalog,
    station_candidates_for_location,
)


class SHMUConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SHMU."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self):
        self._stations: list[LocationOption] = []
        self._locations: list[LocationOption] = []
        self._selected_location: LocationOption | None = None
        self._verify_ssl = True

    async def async_step_user(self, user_input=None):
        """Select a forecast locality and SSL policy."""
        if user_input is not None:
            self._verify_ssl = user_input["verify_ssl"]
            try:
                await self._async_load_catalog()
            except Exception:
                return self._show_user_form(errors={"base": "cannot_connect"})
            self._selected_location = next(
                (
                    location
                    for location in self._locations
                    if location.value == user_input["location_id"]
                ),
                None,
            )
            if self._selected_location is None:
                return self._show_user_form(errors={"base": "invalid_location"})
            candidates = station_candidates_for_location(
                self._selected_location, self._stations
            )
            if len(candidates) == 1:
                return self._create_location_entry(candidates[0])
            return await self.async_step_station()

        try:
            await self._async_load_catalog()
        except Exception:
            return self._show_user_form(errors={"base": "cannot_connect"})
        return self._show_user_form(errors={})

    def _show_user_form(self, errors):
        choices = {location.value: location.label for location in self._locations}
        location_key = vol.Required("location_id")
        if "31396" in choices:
            location_key = vol.Required("location_id", default="31396")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    location_key: vol.In(choices),
                    vol.Optional("verify_ssl", default=True): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_station(self, user_input=None):
        """Select a station when a locality has zero or multiple matches."""
        if self._selected_location is None:
            return await self.async_step_user()
        candidates = station_candidates_for_location(
            self._selected_location, self._stations
        )
        if not candidates:
            candidates = self._stations
        choices = {station.value: station.label for station in candidates}
        errors = {}
        if user_input is not None:
            station = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.value == user_input["station_id"]
                ),
                None,
            )
            if station is not None:
                return self._create_location_entry(station)
            errors = {"base": "invalid_station"}
        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {vol.Required("station_id"): vol.In(choices)}
            ),
            errors=errors,
        )

    async def _async_load_catalog(self):
        if self._stations and self._locations:
            return
        self._stations, self._locations = await async_fetch_location_catalog(
            async_get_clientsession(self.hass), self._verify_ssl
        )

    def _create_location_entry(self, station: LocationOption):
        location = self._selected_location
        assert location is not None
        return self.async_create_entry(
            title=location.label,
            data={
                "location_name": location.label,
                "station_id": station.value,
                "meteogram_id": location.value,
                "verify_ssl": self._verify_ssl,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Create the options flow."""
        return SHMUOptionsFlowHandler(config_entry)


class SHMUOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle SHMU options."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Keep only the supported SSL override in the options UI."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "verify_ssl",
                        default=self._config_entry.options.get(
                            "verify_ssl",
                            self._config_entry.data.get("verify_ssl", True),
                        ),
                    ): bool,
                }
            ),
        )
