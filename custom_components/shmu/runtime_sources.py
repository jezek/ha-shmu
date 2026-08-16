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
    display_name: str = ""


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
                        display_name=str(data.get("station_name") or station_id),
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
                display_name=str(data.get("area_name") or area_id),
            )
        )
    return result


def source_unique_id(
    domain: str,
    entry_id: str,
    source: RuntimeSource,
    suffix: str,
) -> str:
    """Return a legacy-preserving or child-scoped entity unique ID."""
    if source.preserve_legacy_ids:
        return f"{domain}_{entry_id}_{suffix}"
    return f"{domain}_{entry_id}_{source.subentry_id}_{suffix}"


def source_device_identifier(
    domain: str,
    entry_id: str,
    source: RuntimeSource,
    legacy_suffix: str | None = None,
) -> tuple[str, str]:
    """Return a stable device identifier for migrated and newly added sources."""
    if source.preserve_legacy_ids:
        identifier = entry_id
        if legacy_suffix:
            identifier = f"{identifier}_{legacy_suffix}"
        return domain, identifier
    identifier = f"{entry_id}_{source.subentry_id}"
    if legacy_suffix:
        identifier = f"{identifier}_{legacy_suffix}"
    return domain, identifier
