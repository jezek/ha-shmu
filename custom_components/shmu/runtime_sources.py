"""Resolve config subentries into independent SHMU runtime sources."""

from dataclasses import dataclass
from typing import Any, Iterable

from .subentry_migration import (
    MODEL_ALADIN,
    MODEL_ECMWF,
    SUBENTRY_LIVE_STATION,
    SUBENTRY_METEOGRAM,
)


@dataclass(frozen=True)
class RuntimeSource:
    """One independently configured source below a location container."""

    subentry_id: str
    source_type: str
    source_id: str
    model: str | None
    preserve_legacy_ids: bool = False


def runtime_sources(subentries: Iterable[Any]) -> list[RuntimeSource]:
    """Return validated runtime source descriptors in stable ID order."""
    result: list[RuntimeSource] = []
    for subentry in sorted(subentries, key=lambda item: item.subentry_id):
        data = subentry.data
        if subentry.subentry_type == SUBENTRY_LIVE_STATION:
            station_id = str(data.get("station_id") or "").strip()
            if station_id:
                result.append(
                    RuntimeSource(
                        subentry_id=subentry.subentry_id,
                        source_type=SUBENTRY_LIVE_STATION,
                        source_id=station_id,
                        model=None,
                        preserve_legacy_ids=bool(data.get("preserve_legacy_ids")),
                    )
                )
            continue

        if subentry.subentry_type != SUBENTRY_METEOGRAM:
            continue
        model = str(data.get("model") or "").lower()
        area_id = str(data.get("area_id") or "").strip()
        if model not in {MODEL_ALADIN, MODEL_ECMWF} or not area_id:
            continue
        result.append(
            RuntimeSource(
                subentry_id=subentry.subentry_id,
                source_type=SUBENTRY_METEOGRAM,
                source_id=area_id,
                model=model,
                preserve_legacy_ids=bool(data.get("preserve_legacy_ids")),
            )
        )
    return result
