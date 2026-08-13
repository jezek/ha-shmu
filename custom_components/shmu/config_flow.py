"""Configuration flow for SHMU."""

from typing import Any, override

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
import voluptuous as vol

from .const import DOMAIN
from .location_catalog import LocationOption, async_fetch_location_catalog

SUBENTRY_LIVE_STATION = "live_station"
SUBENTRY_METEOGRAM = "meteogram"
MODEL_ALADIN = "aladin"
MODEL_ECMWF = "ecmwf"


class SHMUConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SHMU."""

    VERSION = 2
    MINOR_VERSION = 0

    @override
    async def async_step_user(self, user_input=None):
        """Create an initially empty, user-named location container."""
        if user_input is not None:
            location_name = user_input["location_name"].strip()
            if location_name:
                return self.async_create_entry(
                    title=location_name,
                    data={
                        "location_name": location_name,
                        "verify_ssl": user_input["verify_ssl"],
                    },
                )
            return self._show_user_form(errors={"location_name": "invalid_item"})
        return self._show_user_form(errors={})

    def _show_user_form(self, errors):
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("location_name", default="Pezinok"): str,
                    vol.Optional("verify_ssl", default=True): bool,
                }
            ),
            errors=errors,
        )

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return source types supported below one location container."""
        return {
            SUBENTRY_LIVE_STATION: SHMUSubentryFlow,
            SUBENTRY_METEOGRAM: SHMUSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Create the options flow."""
        return SHMUOptionsFlowHandler(config_entry)


class SHMUSubentryFlow(config_entries.ConfigSubentryFlow):
    """Create validated station and meteogram source subentries."""

    def __init__(self) -> None:
        super().__init__()
        self._stations: list[LocationOption] = []
        self._areas: list[LocationOption] = []
        self._model: str | None = None

    async def _async_load_catalog(self) -> None:
        if self._stations and self._areas:
            return
        entry = self._get_entry()
        verify_ssl = entry.options.get(
            "verify_ssl", entry.data.get("verify_ssl", True)
        )
        self._stations, self._areas = await async_fetch_location_catalog(
            async_get_clientsession(self.hass), verify_ssl
        )

    def _options(self, values: list[LocationOption]) -> list[SelectOptionDict]:
        return [SelectOptionDict(value=item.value, label=item.label) for item in values]

    def _find(self, values: list[LocationOption], value: str) -> LocationOption | None:
        return next((item for item in values if item.value == value), None)

    def _duplicate(self, unique_id: str) -> bool:
        return any(
            subentry.unique_id == unique_id
            for subentry in self._get_entry().subentries.values()
        )

    async def async_step_live_station(self, user_input=None):
        """Add one independently selected current-observation station."""
        try:
            await self._async_load_catalog()
        except Exception:
            return self.async_abort(reason="cannot_connect")
        errors = {}
        if user_input is not None:
            station = self._find(self._stations, user_input["station_id"])
            if station is None:
                errors["base"] = "invalid_item"
            else:
                unique_id = f"{SUBENTRY_LIVE_STATION}:{station.value}"
                if self._duplicate(unique_id):
                    errors["base"] = "already_configured"
                else:
                    return self.async_create_entry(
                        title=station.label,
                        unique_id=unique_id,
                        data={"station_id": station.value, "station_name": station.label},
                    )
        return self.async_show_form(
            step_id=SUBENTRY_LIVE_STATION,
            data_schema=vol.Schema(
                {
                    vol.Required("station_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=self._options(self._stations),
                            custom_value=True,
                            sort=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_meteogram(self, user_input=None):
        """Choose a forecast model before selecting its independent area."""
        if user_input is not None:
            self._model = user_input["model"]
            return await self.async_step_meteogram_area()
        return self.async_show_form(
            step_id=SUBENTRY_METEOGRAM,
            data_schema=vol.Schema(
                {
                    vol.Required("model"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=MODEL_ALADIN, label="ALADIN"),
                                SelectOptionDict(value=MODEL_ECMWF, label="ECMWF"),
                            ],
                            sort=True,
                        )
                    )
                }
            ),
        )

    async def async_step_meteogram_area(self, user_input=None):
        """Add one validated model/area forecast source."""
        if self._model not in {MODEL_ALADIN, MODEL_ECMWF}:
            return await self.async_step_meteogram()
        try:
            await self._async_load_catalog()
        except Exception:
            return self.async_abort(reason="cannot_connect")
        errors = {}
        if user_input is not None:
            area = self._find(self._areas, user_input["area_id"])
            if area is None:
                errors["base"] = "invalid_item"
            else:
                unique_id = f"{SUBENTRY_METEOGRAM}:{self._model}:{area.value}"
                if self._duplicate(unique_id):
                    errors["base"] = "already_configured"
                else:
                    return self.async_create_entry(
                        title=f"{area.label} — {self._model.upper()}",
                        unique_id=unique_id,
                        data={
                            "model": self._model,
                            "area_id": area.value,
                            "area_name": area.label,
                        },
                    )
        return self.async_show_form(
            step_id="meteogram_area",
            data_schema=vol.Schema(
                {
                    vol.Required("area_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=self._options(self._areas),
                            custom_value=True,
                            sort=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input=None):
        """Dispatch a new flow to the requested subentry type."""
        if self._subentry_type == SUBENTRY_METEOGRAM:
            return await self.async_step_meteogram(user_input)
        return await self.async_step_live_station(user_input)


class SHMUOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle SHMU options."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Keep only the parent SSL policy in the options UI."""
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
