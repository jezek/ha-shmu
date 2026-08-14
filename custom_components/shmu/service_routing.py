"""Pure helpers for routing services to source-scoped coordinators."""

from __future__ import annotations


def forecast_coordinator(entry_data, model: str, subentry_id: str | None = None):
    """Resolve one forecast coordinator, rejecting ambiguous selections."""
    coordinators = entry_data.get("coordinators", {})
    if subentry_id:
        coordinator = coordinators.get(subentry_id)
        if coordinator is None:
            raise ValueError(f"Unknown SHMU subentry_id: {subentry_id}")
        if getattr(coordinator.source, "model", None) != model:
            raise ValueError(
                f"SHMU subentry_id {subentry_id} is not a {model} source"
            )
        return coordinator

    matches = [
        coordinator
        for coordinator in coordinators.values()
        if getattr(coordinator.source, "model", None) == model
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Set subentry_id when the selected SHMU entry has {len(matches)} "
            f"{model} sources"
        )
    return matches[0]
