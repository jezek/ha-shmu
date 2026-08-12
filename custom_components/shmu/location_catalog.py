"""Discover SHMU station and meteogram choices from official selectors."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Iterable


CURRENT_STATIONS_URL = (
    "https://www.shmu.sk/sk/?id=meteo_apocasie_sk&ii=11815&page=1"
)
ECMWF_LOCATIONS_URL = (
    "https://www.shmu.sk/sk/?id=meteo_num_mgram10&nwp_mesto=32737&page=1"
)


@dataclass(frozen=True)
class LocationOption:
    """One option exposed by an official SHMU HTML selector."""

    value: str
    label: str


class _SelectOptionsParser(HTMLParser):
    def __init__(self, select_name: str) -> None:
        super().__init__(convert_charrefs=True)
        self._select_name = select_name
        self._in_select = False
        self._option_value: str | None = None
        self._option_text: list[str] = []
        self.options: list[LocationOption] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "select":
            self._in_select = (
                attributes.get("name") == self._select_name
                or attributes.get("id") == self._select_name
            )
        elif tag == "option" and self._in_select:
            self._option_value = attributes.get("value")
            self._option_text = []

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option_value is not None:
            value = self._option_value.strip()
            label = " ".join("".join(self._option_text).split())
            if value.isdigit() and label:
                self.options.append(LocationOption(value=value, label=label))
            self._option_value = None
            self._option_text = []
        elif tag == "select" and self._in_select:
            self._in_select = False


def parse_selector_options(html: str, select_name: str) -> list[LocationOption]:
    """Parse numeric options from one named SHMU selector."""
    parser = _SelectOptionsParser(select_name)
    parser.feed(html)
    if not parser.options:
        raise ValueError(f"SHMU selector {select_name!r} contains no numeric options")
    return parser.options


async def async_fetch_location_catalog(session, verify_ssl: bool = True):
    """Fetch current-station and ECMWF-location catalogues from SHMU."""
    stations_html = await _async_fetch_text(session, CURRENT_STATIONS_URL, verify_ssl)
    locations_html = await _async_fetch_text(session, ECMWF_LOCATIONS_URL, verify_ssl)
    return (
        parse_selector_options(stations_html, "station_id"),
        parse_selector_options(locations_html, "nwp_mesto"),
    )


async def _async_fetch_text(session, url: str, verify_ssl: bool) -> str:
    kwargs = {} if verify_ssl else {"ssl": False}
    async with session.get(url, **kwargs) as response:
        if response.status != 200:
            raise ValueError(f"SHMU location catalogue returned HTTP {response.status}")
        return await response.text()


def station_candidates_for_location(
    location: LocationOption,
    stations: Iterable[LocationOption],
) -> list[LocationOption]:
    """Return exact or locality-prefix station matches for a meteogram place."""
    stations = list(stations)
    full_location_key = _label_key(location.label)
    exact = [
        station
        for station in stations
        if _label_key(station.label) == full_location_key
    ]
    if exact:
        return exact
    location_key = _locality_key(location.label)
    return [
        station
        for station in stations
        if _locality_key(station.label) == location_key
    ]


def _label_key(label: str) -> str:
    return " ".join(label.casefold().split())


def _locality_key(label: str) -> str:
    return _label_key(re.split(r"\s+[-–—]\s+|,|\s*\(", label, maxsplit=1)[0])
