"""SHMU ALADIN forecast normalization helpers."""

from __future__ import annotations

import ssl
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import math
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .grib import decode_nearest_lambert_value, find_product_message, iter_grib2_messages

KELVIN_OFFSET = 273.15
USER_AGENT = "ha-shmu-aladin/1.0"
ALADIN_SK_4_5KM_BASE_URL = (
    "https://opendata.shmu.sk/meteorology/weather/nwp/aladin/sk/4.5km"
)
TEMPERATURE_2M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 0,
    "parameter_number": 0,
    "first_surface_type": 103,
    "first_surface_scaled_value": 2,
}
WIND_U_10M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 2,
    "parameter_number": 2,
    "first_surface_type": 103,
    "first_surface_scaled_value": 10,
}
WIND_V_10M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 2,
    "parameter_number": 3,
    "first_surface_type": 103,
    "first_surface_scaled_value": 10,
}
GUST_U_10M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 2,
    "parameter_number": 23,
    "first_surface_type": 103,
    "first_surface_scaled_value": 10,
}
GUST_V_10M_SELECTOR = {
    "discipline": 0,
    "parameter_category": 2,
    "parameter_number": 24,
    "first_surface_type": 103,
    "first_surface_scaled_value": 10,
}
PRECIPITATION_SELECTOR = {
    "discipline": 0,
    "parameter_category": 1,
    "parameter_number": 193,
    "first_surface_type": 1,
    "first_surface_scaled_value": 0,
}
CLOUD_COVER_SELECTOR = {
    "discipline": 192,
    "parameter_category": 128,
    "parameter_number": 164,
    "first_surface_type": 1,
    "first_surface_scaled_value": 0,
}
DEFAULT_RUN_HOURS = (0, 6, 12, 18)
DEFAULT_RUN_AVAILABILITY_LAG = timedelta(hours=6)
ALADIN_SK_FORECAST_HORIZON_BY_RUN_HOUR = {
    0: 102,
    6: 72,
    12: 72,
    18: 72,
}


def expected_lead_hours(model_run_time: datetime) -> tuple[int, ...]:
    """Return the evidence-backed complete lead range for an ALADIN run.

    SHMU's published metadata describes the fields but does not declare a
    per-run horizon. Its retained OpenData directories consistently publish
    00 UTC runs through lead 102 and 06/12/18 UTC runs through lead 72.
    Unknown issue hours fail closed instead of guessing a shorter horizon.
    """
    run_hour = _as_utc(model_run_time).hour
    try:
        final_lead = ALADIN_SK_FORECAST_HORIZON_BY_RUN_HOUR[run_hour]
    except KeyError as error:
        raise ValueError(
            f"no expected ALADIN forecast horizon for {run_hour:02d} UTC run"
        ) from error
    return tuple(range(final_lead + 1))


def grib_url(model_run_time: datetime, lead_hours: int) -> str:
    """Return the SHMU OpenData ALADIN SK 4.5 km GRIB URL for one lead."""
    if lead_hours < 0:
        raise ValueError("lead_hours must not be negative")
    model_run_time = _as_utc(model_run_time)
    run_date, run_hour = _run_path_parts(model_run_time)
    lead = f"{lead_hours:03d}"
    return (
        f"{run_url(model_run_time)}/"
        f"al-grib_sk_{lead}-{run_date}-{run_hour}-nwp-.grb"
    )


def run_id(model_run_time: datetime) -> str:
    """Return a stable SHMU ALADIN run id for cache unchanged checks."""
    run_date, run_hour = _run_path_parts(_as_utc(model_run_time))
    return f"aladin-sk-4.5km-{run_date}-{run_hour}"


def run_url(model_run_time: datetime) -> str:
    """Return the SHMU OpenData ALADIN run directory URL."""
    run_date, run_hour = _run_path_parts(_as_utc(model_run_time))
    return f"{ALADIN_SK_4_5KM_BASE_URL}/{run_date}/{run_hour}"


def latest_model_run_time(
    now: datetime,
    *,
    run_hours: Iterable[int] = DEFAULT_RUN_HOURS,
    availability_lag: timedelta = DEFAULT_RUN_AVAILABILITY_LAG,
) -> datetime:
    """Return the latest UTC model run time that should be safe to fetch."""
    reference = _as_utc(now) - availability_lag
    hours = tuple(sorted(run_hours))
    if not hours:
        raise ValueError("run_hours must not be empty")
    if any(hour < 0 or hour > 23 for hour in hours):
        raise ValueError("run_hours must contain UTC hours in 0..23")

    for hour in reversed(hours):
        candidate = reference.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= reference:
            return candidate

    previous_day = reference - timedelta(days=1)
    return previous_day.replace(
        hour=hours[-1],
        minute=0,
        second=0,
        microsecond=0,
    )


def download_grib_lead(
    model_run_time: datetime,
    lead_hours: int,
    *,
    timeout: int = 30,
    opener=urlopen,
) -> tuple[int, bytes]:
    """Download one SHMU OpenData ALADIN GRIB lead file."""
    url = grib_url(model_run_time, lead_hours)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=timeout) as response:
        return lead_hours, response.read()


def opener_for_verify_ssl(verify_ssl: bool):
    """Return a urlopen-compatible opener for the requested SSL policy."""
    if verify_ssl:
        return urlopen

    context = ssl._create_unverified_context()

    def _open(request, timeout=30):
        return urlopen(request, timeout=timeout, context=context)

    return _open


def download_grib_leads(
    model_run_time: datetime,
    lead_hours: Iterable[int],
    *,
    timeout: int = 30,
    opener=urlopen,
    stop_at_first_not_found: bool = False,
) -> list[tuple[int, bytes]]:
    """Download multiple SHMU OpenData ALADIN GRIB lead files."""
    downloaded = []
    for lead in lead_hours:
        try:
            downloaded.append(
                download_grib_lead(
                    model_run_time,
                    lead,
                    timeout=timeout,
                    opener=opener,
                )
            )
        except HTTPError as err:
            if stop_at_first_not_found and err.code == 404 and downloaded:
                err.close()
                break
            raise
    return downloaded


def temperature_payload(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    values: Iterable[tuple[int, float | None]],
) -> dict[str, Any]:
    """Build helper-compatible forecast JSON from ALADIN 2 m temperatures."""
    model_run_time = _as_utc(model_run_time)
    rows: list[dict[str, Any]] = []
    for lead_hours, temperature_k in values:
        valid_time = model_run_time + timedelta(hours=lead_hours)
        rows.append(
            {
                "valid_time": _format_utc(valid_time),
                "lead_hours": lead_hours,
                "temperature": None
                if temperature_k is None
                else round(temperature_k - KELVIN_OFFSET, 3),
            }
        )

    return {
        "model_run_time": _format_utc(model_run_time),
        "source_url": source_url,
        "source_run_id": source_run_id,
        "rows": rows,
    }


def forecast_payload(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    values: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build helper-compatible forecast JSON from decoded ALADIN fields."""
    model_run_time = _as_utc(model_run_time)
    rows: list[dict[str, Any]] = []
    for value in values:
        lead_hours = int(value["lead_hours"])
        valid_time = model_run_time + timedelta(hours=lead_hours)
        rows.append(
            {
                "valid_time": _format_utc(valid_time),
                "lead_hours": lead_hours,
                "temperature": _round_optional(value.get("temperature_c")),
                "wind_speed": _round_optional(value.get("wind_speed")),
                "wind_direction": _round_optional(value.get("wind_direction")),
                "wind_gust": _round_optional(value.get("wind_gust")),
                "cloud_cover": _round_optional(value.get("cloud_cover")),
                "precipitation_amount": _round_optional(
                    value.get("precipitation_amount")
                ),
            }
        )

    return {
        "model_run_time": _format_utc(model_run_time),
        "source_url": source_url,
        "source_run_id": source_run_id,
        "rows": rows,
    }


def temperature_payload_from_grib_leads(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    latitude: float,
    longitude: float,
    grib_leads: Iterable[tuple[int, bytes]],
) -> dict[str, Any]:
    """Build helper-compatible temperature JSON from ALADIN GRIB lead files."""
    values: list[tuple[int, float | None]] = []
    for lead_hours, data in grib_leads:
        message = find_product_message(
            iter_grib2_messages(data),
            forecast_time=lead_hours,
            **TEMPERATURE_2M_SELECTOR,
        )
        if message is None:
            raise ValueError(f"missing 2 m temperature field for lead {lead_hours}")
        value = decode_nearest_lambert_value(message, latitude, longitude)
        values.append((lead_hours, value.value))

    return temperature_payload(
        model_run_time=model_run_time,
        source_url=source_url,
        source_run_id=source_run_id,
        values=values,
    )


def forecast_payload_from_grib_leads(
    *,
    model_run_time: datetime,
    source_url: str,
    source_run_id: str,
    latitude: float,
    longitude: float,
    grib_leads: Iterable[tuple[int, bytes]],
) -> dict[str, Any]:
    """Build helper-compatible forecast JSON from ALADIN GRIB lead files."""
    values: list[dict[str, Any]] = []
    for lead_hours, data in grib_leads:
        messages = tuple(iter_grib2_messages(data))
        temperature_k = _optional_value(
            messages,
            selector=TEMPERATURE_2M_SELECTOR,
            forecast_time=lead_hours,
            latitude=latitude,
            longitude=longitude,
        )
        if temperature_k is None:
            continue
        wind_u = _optional_value(
            messages,
            selector=WIND_U_10M_SELECTOR,
            forecast_time=lead_hours,
            latitude=latitude,
            longitude=longitude,
        )
        wind_v = _optional_value(
            messages,
            selector=WIND_V_10M_SELECTOR,
            forecast_time=lead_hours,
            latitude=latitude,
            longitude=longitude,
        )
        gust_u = _optional_value(
            messages,
            selector=GUST_U_10M_SELECTOR,
            forecast_time=None,
            latitude=latitude,
            longitude=longitude,
        )
        gust_v = _optional_value(
            messages,
            selector=GUST_V_10M_SELECTOR,
            forecast_time=None,
            latitude=latitude,
            longitude=longitude,
        )
        precipitation_amount = _optional_value(
            messages,
            selector=PRECIPITATION_SELECTOR,
            forecast_time=None,
            latitude=latitude,
            longitude=longitude,
        )
        cloud_fraction = _optional_value(
            messages,
            selector=CLOUD_COVER_SELECTOR,
            forecast_time=lead_hours,
            latitude=latitude,
            longitude=longitude,
        )
        values.append(
            {
                "lead_hours": lead_hours,
                "temperature_c": temperature_k - KELVIN_OFFSET,
                "wind_speed": _vector_speed(wind_u, wind_v),
                "wind_direction": _wind_direction(wind_u, wind_v),
                "wind_gust": _vector_speed(gust_u, gust_v),
                "cloud_cover": None
                if cloud_fraction is None
                else max(0.0, min(100.0, cloud_fraction * 100.0)),
                "precipitation_amount": precipitation_amount,
            }
        )

    if not values:
        raise ValueError("no usable ALADIN forecast leads contained 2 m temperature fields")

    return forecast_payload(
        model_run_time=model_run_time,
        source_url=source_url,
        source_run_id=source_run_id,
        values=values,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("model_run_time must include timezone")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_path_parts(model_run_time: datetime) -> tuple[str, str]:
    return model_run_time.strftime("%Y%m%d"), model_run_time.strftime("%H%M")


def _required_value(
    messages,
    *,
    selector: dict[str, int],
    forecast_time: int | None,
    latitude: float,
    longitude: float,
    label: str,
    lead_hours: int,
) -> float:
    value = _optional_value(
        messages,
        selector=selector,
        forecast_time=forecast_time,
        latitude=latitude,
        longitude=longitude,
    )
    if value is None:
        raise ValueError(f"missing {label} field for lead {lead_hours}")
    return value


def _optional_value(
    messages,
    *,
    selector: dict[str, int],
    forecast_time: int | None,
    latitude: float,
    longitude: float,
) -> float | None:
    message = find_product_message(
        messages,
        forecast_time=forecast_time,
        **selector,
    )
    if message is None:
        return None
    return decode_nearest_lambert_value(message, latitude, longitude).value


def _vector_speed(u_value: float | None, v_value: float | None) -> float | None:
    if u_value is None or v_value is None:
        return None
    return math.hypot(u_value, v_value)


def _wind_direction(u_value: float | None, v_value: float | None) -> float | None:
    if u_value is None or v_value is None:
        return None
    if u_value == 0 and v_value == 0:
        return None
    return (270.0 - math.degrees(math.atan2(v_value, u_value))) % 360.0


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
