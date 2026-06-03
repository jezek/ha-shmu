"""Normalized SHMU forecast helper contract.

This module deliberately stays dependency-free. The first forecast integration
boundary is compact JSON from an external helper/cache, not direct GRIB decoding
inside the Home Assistant custom component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any


@dataclass(frozen=True)
class ForecastRow:
    """A single normalized forecast row for one valid time."""

    model_run_time: datetime
    valid_time: datetime
    lead_hours: float
    temperature: float | None
    pressure: float | None
    wind_speed: float | None
    wind_direction: float | None
    wind_gust: float | None
    cloud_cover: float | None
    precipitation_amount: float | None
    source_url: str
    source_run_id: str

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-serializable row data."""
        return {
            "model_run_time": _format_datetime(self.model_run_time),
            "valid_time": _format_datetime(self.valid_time),
            "lead_hours": self.lead_hours,
            "temperature": self.temperature,
            "pressure": self.pressure,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "wind_gust": self.wind_gust,
            "cloud_cover": self.cloud_cover,
            "precipitation_amount": self.precipitation_amount,
            "source_url": self.source_url,
            "source_run_id": self.source_run_id,
        }


def parse_helper_forecast(payload: dict[str, Any]) -> list[ForecastRow]:
    """Parse compact helper/cache JSON into normalized forecast rows."""
    model_run_time = _parse_datetime(_required(payload, "model_run_time"))
    source_url = str(_required(payload, "source_url"))
    source_run_id = str(_required(payload, "source_run_id"))
    rows = _required(payload, "rows")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")

    parsed: list[ForecastRow] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"rows[{index}] must be an object")
        parsed.append(
            _parse_row(
                item,
                model_run_time=model_run_time,
                source_url=source_url,
                source_run_id=source_run_id,
                index=index,
            )
        )
    return parsed


class ForecastCache:
    """Tiny JSON file cache for helper-produced normalized forecast rows."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def load(self) -> list[ForecastRow]:
        """Load and parse cached helper output."""
        with self._path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("cached forecast payload must be an object")
        return parse_helper_forecast(payload)

    def save(self, rows: list[ForecastRow]) -> None:
        """Persist rows as compact helper-compatible JSON."""
        if not rows:
            raise ValueError("cannot save an empty forecast cache")
        first = rows[0]
        payload = {
            "model_run_time": _format_datetime(first.model_run_time),
            "source_url": first.source_url,
            "source_run_id": first.source_run_id,
            "rows": [
                {
                    key: value
                    for key, value in row.as_dict().items()
                    if key not in {"model_run_time", "source_url", "source_run_id"}
                }
                for row in rows
            ],
        }
        self.save_payload(payload)

    def save_payload(self, payload: dict[str, Any]) -> None:
        """Persist raw helper payload atomically after validating it."""
        parse_helper_forecast(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self._path)


def _parse_row(
    item: dict[str, Any],
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    index: int,
) -> ForecastRow:
    valid_time = _parse_datetime(_required(item, "valid_time"))
    lead_hours = item.get("lead_hours")
    if lead_hours is None:
        lead_hours = (valid_time - model_run_time).total_seconds() / 3600
    lead_hours = _float(lead_hours, f"rows[{index}].lead_hours")
    if lead_hours < 0:
        raise ValueError(f"rows[{index}].lead_hours must be non-negative")

    return ForecastRow(
        model_run_time=model_run_time,
        valid_time=valid_time,
        lead_hours=lead_hours,
        temperature=_optional_float(item.get("temperature"), f"rows[{index}].temperature"),
        pressure=_optional_float(item.get("pressure"), f"rows[{index}].pressure"),
        wind_speed=_optional_float(item.get("wind_speed"), f"rows[{index}].wind_speed"),
        wind_direction=_optional_float(item.get("wind_direction"), f"rows[{index}].wind_direction"),
        wind_gust=_optional_float(item.get("wind_gust"), f"rows[{index}].wind_gust"),
        cloud_cover=_optional_float(item.get("cloud_cover"), f"rows[{index}].cloud_cover"),
        precipitation_amount=_optional_float(
            item.get("precipitation_amount"),
            f"rows[{index}].precipitation_amount",
        ),
        source_url=source_url,
        source_run_id=source_run_id,
    )


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValueError(f"missing required field: {key}")
    return payload[key]


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _float(value, field_name)


def _float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{field_name} must be numeric") from err


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime value must be a string")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("datetime value must include timezone")
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
