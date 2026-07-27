"""Registry migrations for renamed SHMU entities and devices."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


async def async_migrate_legacy_ecmwf_registry(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Migrate EPSGRAM-named registry records to ECMWF meteogram names."""
    entity_registry = er.async_get(hass)
    unique_id_migrations = {
        "button": (
            f"{DOMAIN}_{entry_id}_refresh_ecmwf_epsgram_cache",
            f"{DOMAIN}_{entry_id}_refresh_ecmwf_meteogram_cache",
        ),
        "weather": (
            f"{DOMAIN}_{entry_id}_ecmwf_epsgram_weather",
            f"{DOMAIN}_{entry_id}_ecmwf_meteogram_weather",
        ),
    }
    for platform, (legacy_unique_id, new_unique_id) in unique_id_migrations.items():
        legacy_entity_id = entity_registry.async_get_entity_id(
            platform,
            DOMAIN,
            legacy_unique_id,
        )
        new_entity_id = entity_registry.async_get_entity_id(
            platform,
            DOMAIN,
            new_unique_id,
        )
        if legacy_entity_id is not None and new_entity_id is None:
            entity_registry.async_update_entity(
                legacy_entity_id,
                new_unique_id=new_unique_id,
            )

    device_registry = dr.async_get(hass)
    legacy_identifier = (DOMAIN, f"{entry_id}_ecmwf_epsgram")
    new_identifier = (DOMAIN, f"{entry_id}_ecmwf_meteogram")
    legacy_device = device_registry.async_get_device(identifiers={legacy_identifier})
    new_device = device_registry.async_get_device(identifiers={new_identifier})
    if legacy_device is not None and new_device is None:
        device_registry.async_update_device(
            legacy_device.id,
            new_identifiers={new_identifier},
        )
