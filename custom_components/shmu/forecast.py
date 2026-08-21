"""Normalized SHMU forecast helper contract.

This module deliberately stays dependency-free. The first forecast integration
boundary is compact JSON from an external helper/cache, not direct GRIB decoding
inside the Home Assistant custom component.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse

PRECIPITATION_THRESHOLD_MM = 0.1
CLEAR_CLOUD_COVER_THRESHOLD = 30.0
FORECAST_SERIES_FIELDS = {
    "temperature",
    "pressure",
    "wind_speed",
    "wind_direction",
    "wind_gust",
    "cloud_cover",
    "precipitation_amount",
}
FORECAST_COMPARISON_DECIMALS = 3
CURRENT_CONDITION_MAX_DISTANCE = timedelta(hours=2)
SPARSE_FORECAST_MAX_BOUNDARY_GAP = timedelta(hours=6)


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

    def info(self, reference_time: datetime | None = None) -> dict[str, Any]:
        """Return compact freshness metadata for the cached helper output."""
        rows = self.load()
        stat = self._path.stat()
        modified_time = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)
        else:
            reference_time = _as_aware_utc(reference_time)

        source_url = rows[0].source_url
        source_filename = Path(unquote(urlparse(source_url).path)).name or None
        formatted_modified_time = _format_datetime(modified_time)
        return {
            "path": os.fspath(self._path),
            "row_count": len(rows),
            "file_modified_time": formatted_modified_time,
            "downloaded_time": formatted_modified_time,
            "age_seconds": max(0.0, (reference_time - modified_time).total_seconds()),
            "model_run_time": _format_datetime(rows[0].model_run_time),
            "oldest_valid_time": _format_datetime(min(row.valid_time for row in rows)),
            "newest_valid_time": _format_datetime(max(row.valid_time for row in rows)),
            "source_run_id": rows[0].source_run_id,
            "source_url": source_url,
            "source_filename": source_filename,
        }

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


def rows_as_hourly_forecast(
    rows: list[ForecastRow],
    reference_time: datetime | None = None,
    is_daytime_at: Callable[[datetime], bool] | None = None,
) -> list[dict[str, Any]]:
    """Convert future rows starting at the nearest upcoming full hour."""
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    cutoff = _next_full_hour(_as_aware_utc(reference_time))
    forecasts: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda row: row.valid_time):
        if row.valid_time < cutoff:
            continue
        forecast = _row_as_weather_forecast(row)
        if is_daytime_at is not None:
            is_daytime = is_daytime_at(row.valid_time)
            forecast["is_daytime"] = is_daytime
            if not is_daytime and forecast["condition"] in {"sunny", "partlycloudy"}:
                forecast["condition"] = "clear-night"
        forecasts.append(forecast)
    return forecasts


def current_condition(
    rows: list[ForecastRow],
    reference_time: datetime,
    precipitation_amount: float | None = None,
    is_daytime_at: Callable[[datetime], bool] | None = None,
    max_distance: timedelta = CURRENT_CONDITION_MAX_DISTANCE,
) -> str:
    """Return the observed-rain or nearest fresh model condition."""
    if (
        precipitation_amount is not None
        and float(precipitation_amount) >= PRECIPITATION_THRESHOLD_MM
    ):
        return "rainy"

    reference_utc = _as_aware_utc(reference_time)
    if not rows:
        return "cloudy"
    nearest = min(
        rows,
        key=lambda row: (
            abs(row.valid_time - reference_utc),
            row.valid_time > reference_utc,
        ),
    )
    if abs(nearest.valid_time - reference_utc) > max_distance:
        return "cloudy"

    condition = _condition_for_row(nearest)
    if (
        is_daytime_at is not None
        and not is_daytime_at(reference_utc)
        and condition in {"sunny", "partlycloudy"}
    ):
        return "clear-night"
    return condition


def rows_as_daily_forecast(
    rows: list[ForecastRow],
    historical_temperatures: dict[datetime, float] | None = None,
    reference_time: datetime | None = None,
    require_hourly_coverage: bool = True,
    time_zone: tzinfo | None = None,
) -> list[dict[str, Any]]:
    """Aggregate rows into daily forecasts in the presentation time zone.

    Forecast rows are UTC, but Home Assistant presents daily cards in its
    configured local time zone.  Grouping by UTC would put a 23:00 UTC shower
    on the previous local calendar day.
    """
    presentation_time_zone = time_zone or timezone.utc
    historical_by_day = _historical_temperatures_by_day(
        historical_temperatures or {}, presentation_time_zone
    )
    days: dict[str, list[ForecastRow]] = {}
    for row in sorted(rows, key=lambda row: row.valid_time):
        day_key = row.valid_time.astimezone(presentation_time_zone).date().isoformat()
        days.setdefault(day_key, []).append(row)

    forecasts: list[dict[str, Any]] = []
    initial_day = min(days, default=None)
    final_day = max(days, default=None)
    reference_day = (
        _as_aware_utc(reference_time).astimezone(presentation_time_zone).date()
        if reference_time is not None
        else None
    )
    for day_key, day_rows in days.items():
        if reference_day is not None and datetime.fromisoformat(day_key).date() < reference_day:
            continue
        historical_day = (
            historical_by_day.get(day_key, {}) if day_key == initial_day else {}
        )
        covered_hours = {
            row.valid_time.astimezone(presentation_time_zone).hour for row in day_rows
        } | set(historical_day)
        if require_hourly_coverage:
            missing_hours = set(range(24)) - covered_hours
            first_covered_hour = min(covered_hours, default=24)
            has_short_current_leading_gap = (
                day_key == initial_day
                and reference_day == datetime.fromisoformat(day_key).date()
                and missing_hours == set(range(first_covered_hour))
                and first_covered_hour <= int(
                    SPARSE_FORECAST_MAX_BOUNDARY_GAP.total_seconds() / 3600
                )
            )
            last_covered_hour = max(covered_hours, default=-1)
            has_short_trailing_horizon_gap = (
                day_key == final_day
                and missing_hours == set(range(last_covered_hour + 1, 24))
                and 24 - (last_covered_hour + 1)
                <= int(SPARSE_FORECAST_MAX_BOUNDARY_GAP.total_seconds() / 3600)
            )
            if missing_hours and not (
                has_short_current_leading_gap or has_short_trailing_horizon_gap
            ):
                continue
        else:
            # ECMWF publishes values every three or six hours and its first
            # local value is not necessarily midnight (for example 02:00 in
            # CEST).  A calendar day is nevertheless complete when samples
            # bracket both local boundaries.  Requiring samples *at* those
            # boundaries made every sparse ECMWF daily forecast disappear.
            day_start = datetime.fromisoformat(day_key).replace(
                tzinfo=presentation_time_zone
            )
            day_end = day_start + timedelta(days=1)
            local_times = [
                row.valid_time.astimezone(presentation_time_zone) for row in rows
            ]
            first_day_sample = min(
                (value for value in local_times if value.date() == day_start.date()),
                default=None,
            )
            has_start_boundary = any(value <= day_start for value in local_times)
            if (
                not has_start_boundary
                and reference_day == day_start.date()
                and first_day_sample is not None
                and first_day_sample - day_start <= SPARSE_FORECAST_MAX_BOUNDARY_GAP
            ):
                # A 00 UTC ECMWF run starts at 02:00 during CEST. Admit today's
                # card when only this short leading boundary is absent; the
                # coordinator records and warns about that approximation.
                has_start_boundary = True
            if not (
                has_start_boundary and any(value >= day_end for value in local_times)
            ):
                continue
        temperatures = [row.temperature for row in day_rows if row.temperature is not None]
        temperatures.extend(
            temperature
            for hour, temperature in historical_day.items()
            if hour
            not in {
                row.valid_time.astimezone(presentation_time_zone).hour
                for row in day_rows
            }
        )
        precipitation = [
            row.precipitation_amount
            for row in day_rows
            if row.precipitation_amount is not None
        ]
        wind_speeds = [row.wind_speed for row in day_rows if row.wind_speed is not None]
        gusts = [row.wind_gust for row in day_rows if row.wind_gust is not None]
        cloud_cover = [row.cloud_cover for row in day_rows if row.cloud_cover is not None]
        has_rain = any(
            row.precipitation_amount is not None
            and row.precipitation_amount >= PRECIPITATION_THRESHOLD_MM
            for row in day_rows
        )
        average_cloud_cover = (
            sum(cloud_cover) / len(cloud_cover) if cloud_cover else None
        )

        forecast: dict[str, Any] = {
            "datetime": _format_datetime(
                datetime.fromisoformat(day_key).replace(
                    hour=12, tzinfo=presentation_time_zone
                )
            ),
            "condition": (
                "rainy" if has_rain else _condition_for_cloud_cover(average_cloud_cover)
            ),
        }
        if temperatures:
            forecast["temperature"] = max(temperatures)
            forecast["templow"] = min(temperatures)
        if precipitation:
            forecast["precipitation"] = sum(precipitation)
        if wind_speeds:
            forecast["wind_speed"] = max(wind_speeds)
        if gusts:
            forecast["wind_gust_speed"] = max(gusts)
        if cloud_cover:
            forecast["cloud_coverage"] = average_cloud_cover
        forecasts.append(forecast)
    return forecasts


def sparse_daily_completion_info(
    rows: list[ForecastRow],
    time_zone: tzinfo,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Describe sparse local days accepted using samples around their boundaries.

    ECMWF values are commonly three hours apart, so a complete local day may
    have no sample exactly at either local midnight.  Keep this calculation
    separate from aggregation so the coordinator can log the approximation
    once per cache refresh and expose its provenance diagnostically.
    """
    local_times = sorted(row.valid_time.astimezone(time_zone) for row in rows)
    reference_day = (
        _as_aware_utc(reference_time).astimezone(time_zone).date()
        if reference_time is not None
        else None
    )
    day_keys = sorted({value.date().isoformat() for value in local_times})
    result = []
    for day_key in day_keys:
        day_start = datetime.fromisoformat(day_key).replace(tzinfo=time_zone)
        day_end = day_start + timedelta(days=1)
        first_day_sample = min(
            (value for value in local_times if value.date() == day_start.date()),
            default=None,
        )
        has_start_boundary = any(value <= day_start for value in local_times)
        if (
            not has_start_boundary
            and reference_day == day_start.date()
            and first_day_sample is not None
            and first_day_sample - day_start <= SPARSE_FORECAST_MAX_BOUNDARY_GAP
        ):
            has_start_boundary = True
        if not (has_start_boundary and any(value >= day_end for value in local_times)):
            continue
        missing_boundaries = [
            label
            for label, boundary in (("start", day_start), ("end", day_end))
            if boundary not in local_times
        ]
        if missing_boundaries:
            result.append(
                {
                    "date": day_key,
                    "missing_boundaries": missing_boundaries,
                }
            )
    return result


def forecast_summary(rows: list[ForecastRow], now: datetime) -> dict[str, Any]:
    """Return compact forecast summary values for practical sensors."""
    now_utc = _as_aware_utc(now)
    future_rows = [row for row in rows if row.valid_time >= now_utc]
    local_tz = now.tzinfo or timezone.utc
    tomorrow = now_utc.astimezone(local_tz).date().toordinal() + 1
    tomorrow_rows = [
        row
        for row in future_rows
        if row.valid_time.astimezone(local_tz).date().toordinal() == tomorrow
    ]
    tomorrow_temperatures = [
        row.temperature for row in tomorrow_rows if row.temperature is not None
    ]

    precipitation_rows = [
        row
        for row in future_rows
        if row.precipitation_amount is not None
        and row.precipitation_amount >= PRECIPITATION_THRESHOLD_MM
    ]
    next_precipitation = min(precipitation_rows, key=lambda row: row.valid_time, default=None)

    gust_rows = [row for row in future_rows if row.wind_gust is not None]
    strongest_gust = max(gust_rows, key=lambda row: row.wind_gust or 0, default=None)

    clear_rows = [
        row
        for row in future_rows
        if row.cloud_cover is not None
        and row.cloud_cover <= CLEAR_CLOUD_COVER_THRESHOLD
        and (row.precipitation_amount is None or row.precipitation_amount < PRECIPITATION_THRESHOLD_MM)
    ]
    next_clear = min(clear_rows, key=lambda row: row.valid_time, default=None)

    return {
        "tomorrow_min_temperature": min(tomorrow_temperatures) if tomorrow_temperatures else None,
        "tomorrow_max_temperature": max(tomorrow_temperatures) if tomorrow_temperatures else None,
        "next_precipitation_time": next_precipitation.valid_time if next_precipitation else None,
        "next_precipitation_amount": (
            next_precipitation.precipitation_amount if next_precipitation else None
        ),
        "strongest_gust_time": strongest_gust.valid_time if strongest_gust else None,
        "strongest_gust_speed": strongest_gust.wind_gust if strongest_gust else None,
        "next_clear_window_time": next_clear.valid_time if next_clear else None,
    }


def forecast_series(
    rows: list[ForecastRow],
    field: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return a compact forecast value series for service/dashboard consumers."""
    _validate_series_field(field)
    start_utc = _as_aware_utc(start) if start is not None else None
    end_utc = _as_aware_utc(end) if end is not None else None

    series = []
    for row in sorted(rows, key=lambda item: item.valid_time):
        if start_utc is not None and row.valid_time < start_utc:
            continue
        if end_utc is not None and row.valid_time > end_utc:
            continue
        value = getattr(row, field)
        if value is None:
            continue
        series.append(
            {
                "valid_time": _format_datetime(row.valid_time),
                "value": value,
                "lead_hours": row.lead_hours,
                "model_run_time": _format_datetime(row.model_run_time),
                "source_run_id": row.source_run_id,
            }
        )
    return series


def forecast_comparison(
    rows: list[ForecastRow],
    observations: list[dict[str, Any]],
    field: str,
    *,
    max_distance_minutes: float = 30.0,
) -> list[dict[str, Any]]:
    """Compare forecast rows against observed values by nearest valid time."""
    _validate_series_field(field)
    if max_distance_minutes < 0:
        raise ValueError("max_distance_minutes must be non-negative")

    forecast_rows = [
        row
        for row in sorted(rows, key=lambda item: item.valid_time)
        if getattr(row, field) is not None
    ]
    max_distance_seconds = max_distance_minutes * 60
    comparison = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"observations[{index}] must be an object")
        observed_time = _parse_observation_time(observation, index)
        observed_value = _optional_float(
            observation.get("value"),
            f"observations[{index}].value",
        )
        if observed_value is None:
            continue
        match = _nearest_row(forecast_rows, observed_time)
        if match is None:
            continue
        distance_seconds = abs((match.valid_time - observed_time).total_seconds())
        if distance_seconds > max_distance_seconds:
            continue
        forecast_value = getattr(match, field)
        error = _rounded_measurement(forecast_value - observed_value)
        comparison.append(
            {
                "observation_time": _format_datetime(observed_time),
                "forecast_valid_time": _format_datetime(match.valid_time),
                "observed_value": observed_value,
                "forecast_value": forecast_value,
                "error": error,
                "abs_error": abs(error),
                "distance_minutes": distance_seconds / 60,
                "lead_hours": match.lead_hours,
                "model_run_time": _format_datetime(match.model_run_time),
                "source_run_id": match.source_run_id,
            }
        )
    return comparison


def _rounded_measurement(value: float) -> float:
    rounded = round(value, FORECAST_COMPARISON_DECIMALS)
    if rounded == 0:
        return 0.0
    return rounded


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


def _validate_series_field(field: str) -> None:
    if field not in FORECAST_SERIES_FIELDS:
        raise ValueError(f"unsupported forecast field: {field}")


def _parse_observation_time(observation: dict[str, Any], index: int) -> datetime:
    if "time" in observation:
        return _parse_datetime(observation["time"])
    if "valid_time" in observation:
        return _parse_datetime(observation["valid_time"])
    raise ValueError(f"observations[{index}] missing time")


def _nearest_row(rows: list[ForecastRow], target_time: datetime) -> ForecastRow | None:
    return min(rows, key=lambda row: abs((row.valid_time - target_time).total_seconds()), default=None)


def _row_as_weather_forecast(row: ForecastRow) -> dict[str, Any]:
    forecast: dict[str, Any] = {
        "datetime": _format_datetime(row.valid_time),
        "condition": _condition_for_row(row),
    }
    optional_fields = {
        "temperature": row.temperature,
        "pressure": row.pressure,
        "wind_speed": row.wind_speed,
        "wind_bearing": row.wind_direction,
        "wind_gust_speed": row.wind_gust,
        "cloud_coverage": row.cloud_cover,
        "precipitation": row.precipitation_amount,
    }
    forecast.update({key: value for key, value in optional_fields.items() if value is not None})
    return forecast


def _condition_for_row(row: ForecastRow) -> str:
    if (
        row.precipitation_amount is not None
        and row.precipitation_amount >= PRECIPITATION_THRESHOLD_MM
    ):
        return "rainy"
    return _condition_for_cloud_cover(row.cloud_cover)


def _condition_for_cloud_cover(cloud_cover: float | None) -> str:
    """Map a point or daily-average cloud percentage to a weather condition."""
    if cloud_cover is None:
        return "cloudy"
    if cloud_cover < 20:
        return "sunny"
    if cloud_cover < 70:
        return "partlycloudy"
    return "cloudy"


def _has_full_day_coverage(rows: list[ForecastRow]) -> bool:
    hours = {row.valid_time.hour for row in rows}
    return min(hours, default=24) == 0 and max(hours, default=-1) == 23


def _historical_temperatures_by_day(
    values: dict[datetime, float],
    presentation_time_zone: tzinfo = timezone.utc,
) -> dict[str, dict[int, float]]:
    by_day: dict[str, dict[int, float]] = {}
    for timestamp, temperature in values.items():
        local_timestamp = _as_aware_utc(timestamp).astimezone(presentation_time_zone)
        by_day.setdefault(local_timestamp.date().isoformat(), {})[
            local_timestamp.hour
        ] = float(temperature)
    return by_day


def _next_full_hour(value: datetime) -> datetime:
    """Return the next full hour, preserving an already exact boundary."""
    boundary = value.replace(minute=0, second=0, microsecond=0)
    if value == boundary:
        return boundary
    return boundary + timedelta(hours=1)


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


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
