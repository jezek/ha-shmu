"""Helpers for SHMU interactive EPSGRAM product metadata."""

from __future__ import annotations

from typing import Any


def latest_station_product(payload: dict[str, Any], product_type: str) -> dict[str, Any]:
    """Return the newest station product entry for a product type."""
    products = payload.get("data")
    if not isinstance(products, list):
        raise ValueError("station products payload must contain a data list")

    matching = [
        item
        for item in products
        if isinstance(item, dict) and item.get("type") == product_type
    ]
    if not matching:
        raise ValueError(f"no station product found for type: {product_type}")

    return max(matching, key=_runtime_key)


def product_json_url(file_link: str) -> str:
    """Return the SHMU JSON URL for a station product file link."""
    clean_link = file_link.lstrip("/")
    return f"https://www.shmu.sk/data/datanwp/json/{clean_link}"


def _runtime_key(item: dict[str, Any]) -> int:
    runtime = item.get("runtime")
    if not isinstance(runtime, int):
        raise ValueError("station product runtime must be an integer")
    return runtime
