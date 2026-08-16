"""Shared entity metadata helpers for SHMU platforms."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .runtime_sources import source_device_identifier, source_unique_id


def _source(coordinator):
    return getattr(coordinator, "source", None)


def aladin_meteogram_page_url(area_id: str) -> str:
    """Return the current official ALADIN meteogram page for an area."""
    return (
        "https://www.shmu.sk/sk/"
        f"?id=meteo_num_mgram&nwp_mesto={area_id}&page=1"
    )


def _identifier(coordinator, legacy_suffix: str | None = None):
    source = _source(coordinator)
    entry_id = coordinator.config_entry.entry_id
    if source is None:
        identifier = entry_id
        if legacy_suffix:
            identifier = f"{identifier}_{legacy_suffix}"
        return DOMAIN, identifier
    return source_device_identifier(DOMAIN, entry_id, source, legacy_suffix)


def entity_unique_id(
    coordinator, suffix: str, *, legacy_unique_id: str | None = None
) -> str:
    """Return the compatible unique ID for an entity below a source."""
    source = _source(coordinator)
    entry_id = coordinator.config_entry.entry_id
    if source is None:
        return legacy_unique_id or f"{DOMAIN}_{entry_id}_{suffix}"
    if source.preserve_legacy_ids and legacy_unique_id:
        return legacy_unique_id
    return source_unique_id(DOMAIN, entry_id, source, suffix)


def station_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for current SHMU station observations."""
    source = _source(coordinator)
    station_id = (
        source.source_id if source else coordinator.config_entry.data["station_id"]
    )
    return DeviceInfo(
        identifiers={_identifier(coordinator)},
        name=f"SHMU Station {station_id}",
        manufacturer="Slovenský hydrometeorologický ústav",
        model="Weather Station",
        configuration_url=(
            "https://opendata.shmu.sk/meteorology/climate/now/data/"
        ),
        sw_version="1.0",
    )


def forecast_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for cache-backed SHMU forecast entities."""
    source = _source(coordinator)
    area_id = source.source_id if source else coordinator.config_entry.data["station_id"]
    values = dict(
        identifiers={_identifier(coordinator, "forecast")},
        name=f"SHMU Forecast {area_id}",
        manufacturer="Slovenský hydrometeorologický ústav",
        model="ALADIN SK 4.5 km Forecast Cache",
        configuration_url=(
            "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km"
        ),
        sw_version="1.0",
    )
    if source is None or source.preserve_legacy_ids:
        values["via_device"] = (DOMAIN, coordinator.config_entry.entry_id)
    return DeviceInfo(**values)


def ecmwf_meteogram_device_info(coordinator) -> DeviceInfo:
    """Return device metadata for ECMWF 10-day meteogram forecast entities."""
    source = _source(coordinator)
    station_id = coordinator.config_entry.data.get("station_id", "")
    meteogram_id = (
        source.source_id
        if source
        else coordinator.config_entry.data.get("meteogram_id", station_id)
    )
    values = dict(
        identifiers={_identifier(coordinator, "ecmwf_meteogram")},
        name=(
            f"SHMU ECMWF 10-day meteogram "
            f"{meteogram_id if source else station_id}"
        ),
        manufacturer="Slovenský hydrometeorologický ústav",
        model="ECMWF 10-day Meteogram Forecast Cache",
        configuration_url="https://www.shmu.sk/data/datanwp/json/ecmwf/",
        sw_version="1.0",
    )
    if source is None or source.preserve_legacy_ids:
        values["via_device"] = (DOMAIN, coordinator.config_entry.entry_id)
    return DeviceInfo(**values)
