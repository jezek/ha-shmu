"""Helpers for SHMU interactive EPSGRAM product metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ECMWF_FIELD_MAP = {
    "temperature": ("Air_temperature_at_2m", "Median"),
    "pressure": ("Mean_sea_level_pressure", "Median"),
    "wind_speed": ("Wind_speed_at_10m", "Median"),
    "wind_gust": ("Wind_gust_at_10m", "Median"),
    "cloud_cover": ("Total_cloud_cover", "Median"),
    "precipitation_amount": ("Total_precipitation", "Median"),
}
WIND_DIRECTION_DEGREES = {
    "N": 0.0,
    "NE": 45.0,
    "E": 90.0,
    "SE": 135.0,
    "S": 180.0,
    "SW": 225.0,
    "W": 270.0,
    "NW": 315.0,
}


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


def ecmwf_helper_payload(payload: dict[str, Any], source_url: str) -> dict[str, Any]:
    """Convert an ECMWF EPSGRAM JSON payload into the helper forecast contract."""
    model_run_time = _parse_datetime(str(payload.get("data_date_time", "")))
    temperature_by_time = _series_by_column(payload, "Air_temperature_at_2m", "Median")
    if not temperature_by_time:
        raise ValueError("ECMWF payload must contain temperature median rows")

    series = {
        name: _series_by_column(payload, field_name, column_name)
        for name, (field_name, column_name) in ECMWF_FIELD_MAP.items()
    }
    wind_direction_by_time = _wind_direction_series(payload)
    source_run_id = _ecmwf_run_id(payload, model_run_time)

    rows: list[dict[str, Any]] = []
    for timestamp in sorted(temperature_by_time):
        valid_time = datetime.fromtimestamp(timestamp, timezone.utc)
        row = {
            "valid_time": _format_datetime(valid_time),
            "lead_hours": round(
                (valid_time - model_run_time).total_seconds() / 3600,
                3,
            ),
        }
        for field_name in ECMWF_FIELD_MAP:
            row[field_name] = series[field_name].get(timestamp)
        row["wind_direction"] = wind_direction_by_time.get(timestamp)
        rows.append(row)

    return {
        "model_run_time": _format_datetime(model_run_time),
        "source_url": source_url,
        "source_run_id": source_run_id,
        "rows": rows,
    }


def _runtime_key(item: dict[str, Any]) -> int:
    runtime = item.get("runtime")
    if not isinstance(runtime, int):
        raise ValueError("station product runtime must be an integer")
    return runtime


def _series_by_column(
    payload: dict[str, Any],
    field_name: str,
    column_name: str,
) -> dict[int, float | None]:
    field = payload.get(field_name)
    if field is None:
        return {}
    if not isinstance(field, dict):
        raise ValueError(f"{field_name} must be an object")
    columns = field.get("columns")
    data = field.get("data")
    if not isinstance(columns, list) or not isinstance(data, list):
        raise ValueError(f"{field_name} must contain columns and data lists")
    try:
        time_index = columns.index("Time")
        value_index = columns.index(column_name)
    except ValueError as err:
        raise ValueError(f"{field_name} must contain Time and {column_name} columns") from err

    result: dict[int, float | None] = {}
    for row_index, row in enumerate(data):
        if not isinstance(row, list):
            raise ValueError(f"{field_name}.data[{row_index}] must be a list")
        if len(row) <= max(time_index, value_index):
            raise ValueError(f"{field_name}.data[{row_index}] is missing required columns")
        timestamp = _timestamp(row[time_index], f"{field_name}.data[{row_index}].Time")
        result[timestamp] = _optional_float(row[value_index])
    return result


def _wind_direction_series(payload: dict[str, Any]) -> dict[int, float | None]:
    field = payload.get("Wind_direction_at_10m")
    if field is None:
        return {}
    if not isinstance(field, dict):
        raise ValueError("Wind_direction_at_10m must be an object")
    columns = field.get("columns")
    data = field.get("data")
    if not isinstance(columns, list) or not isinstance(data, list):
        raise ValueError("Wind_direction_at_10m must contain columns and data lists")
    try:
        time_index = columns.index("Time")
    except ValueError as err:
        raise ValueError("Wind_direction_at_10m must contain Time column") from err

    direction_indices = [
        (index, WIND_DIRECTION_DEGREES[column])
        for index, column in enumerate(columns)
        if column in WIND_DIRECTION_DEGREES
    ]
    if not direction_indices:
        raise ValueError("Wind_direction_at_10m must contain direction columns")

    result: dict[int, float | None] = {}
    for row_index, row in enumerate(data):
        if not isinstance(row, list):
            raise ValueError(f"Wind_direction_at_10m.data[{row_index}] must be a list")
        if len(row) <= max([time_index, *[index for index, _ in direction_indices]]):
            raise ValueError(
                f"Wind_direction_at_10m.data[{row_index}] is missing required columns"
            )
        timestamp = _timestamp(row[time_index], f"Wind_direction_at_10m.data[{row_index}].Time")
        scored = [
            (_optional_float(row[index]), degrees)
            for index, degrees in direction_indices
        ]
        scored = [(score, degrees) for score, degrees in scored if score is not None]
        if not scored:
            result[timestamp] = None
            continue
        score, degrees = max(scored, key=lambda item: item[0])
        result[timestamp] = degrees if score > 0 else None
    return result


def _ecmwf_run_id(payload: dict[str, Any], model_run_time: datetime) -> str:
    station_id = str(payload.get("si_id") or "unknown")
    return f"ecmwf-{station_id}-{_format_datetime(model_run_time)}"


def _parse_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("ECMWF payload must contain data_date_time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as err:
        raise ValueError(f"invalid ECMWF data_date_time: {value}") from err


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any, label: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{label} must be an integer epoch timestamp")
    return value


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
