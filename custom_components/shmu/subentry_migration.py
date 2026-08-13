"""Pure helpers for migrating legacy coupled SHMU config entries."""

from typing import Any

from .const import DEFAULT_STATION_ID

SUBENTRY_LIVE_STATION = "live_station"
SUBENTRY_METEOGRAM = "meteogram"
MODEL_ALADIN = "aladin"
MODEL_ECMWF = "ecmwf"


def legacy_parent_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return version-2 parent data without source-specific fields."""
    location_name = str(data.get("location_name") or "SHMU location").strip()
    return {
        "location_name": location_name or "SHMU location",
        "verify_ssl": bool(data.get("verify_ssl", True)),
    }


def legacy_subentry_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe the child sources represented by one legacy config entry."""
    station_id = str(data.get("station_id") or DEFAULT_STATION_ID)
    result = [
        {
            "subentry_type": SUBENTRY_LIVE_STATION,
            "title": f"Station {station_id}",
            "unique_id": f"{SUBENTRY_LIVE_STATION}:{station_id}",
            "data": {
                "station_id": station_id,
                "station_name": station_id,
                "preserve_legacy_ids": True,
            },
        }
    ]

    meteogram_id = str(data.get("meteogram_id") or "none")
    if meteogram_id != "none":
        for model in (MODEL_ALADIN, MODEL_ECMWF):
            result.append(
                {
                    "subentry_type": SUBENTRY_METEOGRAM,
                    "title": f"Area {meteogram_id} — {model.upper()}",
                    "unique_id": f"{SUBENTRY_METEOGRAM}:{model}:{meteogram_id}",
                    "data": {
                        "model": model,
                        "area_id": meteogram_id,
                        "area_name": meteogram_id,
                        "preserve_legacy_ids": True,
                    },
                }
            )
    return result
