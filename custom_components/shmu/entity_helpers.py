"""Shared entity metadata helpers for SHMU platforms."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def station_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for current SHMU station observations."""
    station_id = coordinator.config_entry.data["station_id"]
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name=f"SHMU Station {station_id}",
        manufacturer="Slovenský hydrometeorologický ústav",
        model="Weather Station",
        sw_version="1.0",
    )


def forecast_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for cache-backed SHMU forecast entities."""
    station_id = coordinator.config_entry.data["station_id"]
    station_identifier = (DOMAIN, coordinator.config_entry.entry_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_forecast")},
        name=f"SHMU Forecast {station_id}",
        manufacturer="Slovenský hydrometeorologický ústav",
        model="ALADIN SK 4.5 km Forecast Cache",
        configuration_url=(
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km"
        ),
        sw_version="1.0",
        via_device=station_identifier,
    )


def ecmwf_epsgram_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for ECMWF EPSGRAM forecast entities."""
    station_id = coordinator.config_entry.data["station_id"]
    station_identifier = (DOMAIN, coordinator.config_entry.entry_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_ecmwf_epsgram")},
        name=f"SHMU ECMWF EPSGRAM {station_id}",
        manufacturer="Slovenský hydrometeorologický ústav",
        model="ECMWF ENS EPSGRAM Forecast Cache",
        configuration_url="https://www.shmu.sk/sk/?page=2673",
        sw_version="1.0",
        via_device=station_identifier,
    )
