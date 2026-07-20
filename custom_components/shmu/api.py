import aiohttp
import async_timeout
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)
SHMU_TIMEZONE = ZoneInfo("Europe/Bratislava")

class SHMUAPI:
    """Class to handle SHMU API communication."""

    def __init__(self, station_id: str, verify_ssl: bool = True):
        """Initialize the API client."""
        self._station_id = station_id
        self._verify_ssl = verify_ssl

    def _generate_url(self):
        """Generate the dynamic URL for SHMU data."""
        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1) #there is delay <1 min in shmu file publish time
        date_str = one_minute_ago.strftime("%Y%m%d")
        time_str = f"{one_minute_ago.strftime('%H')}-{'%02d' % ((one_minute_ago.minute // 5) * 5)}-00"
        return (
            f"https://opendata.shmu.sk/meteorology/climate/now/data/"
            f"{date_str}/aws1min%20-%20{one_minute_ago.strftime('%Y-%m-%d')} {time_str}.json"
        )

    async def fetch_data(self, session: aiohttp.ClientSession):
        """Fetch data from SHMU API."""
        url = self._generate_url()
        _LOGGER.debug("Fetching SHMU data from URL: %s", url)

        try:
            request_kwargs = {}
            if not self._verify_ssl:
                request_kwargs["ssl"] = False

            async with async_timeout.timeout(10):
                async with session.get(url, **request_kwargs) as response:
                    if response.status != 200:
                        raise Exception(f"Error fetching SHMU data: HTTP {response.status} for URL: {url}")
                    data = await response.json()
                    station_data = [
                        item for item in data.get("data", [])
                        if str(item.get("ind_kli")) == self._station_id
                    ]
                    if not station_data:
                        raise Exception(f"No data found for station ID: {self._station_id}")
                    return station_data[0]
        except aiohttp.ClientError as err:
            raise Exception(f"Communication error with SHMU API: {err}")
        except Exception as err:
            raise Exception(f"Unexpected error: {err}")

    async def fetch_temperature_history(
        self,
        session: aiohttp.ClientSession,
        start: datetime,
        end: datetime,
    ) -> dict[datetime, float]:
        """Fetch one latest station temperature sample for each UTC hour."""
        start_utc = _aware_utc(start).replace(minute=0, second=0, microsecond=0)
        end_utc = _aware_utc(end)
        temperatures: dict[datetime, float] = {}
        hour = start_utc
        while hour < end_utc:
            payload = await self._fetch_json(session, _history_url(hour))
            matches = []
            for item in payload.get("data", []):
                if str(item.get("ind_kli")) != self._station_id or item.get("t") is None:
                    continue
                observed = datetime.fromisoformat(str(item.get("minuta"))).replace(
                    tzinfo=timezone.utc
                )
                if observed.replace(minute=0, second=0, microsecond=0) == hour:
                    matches.append((observed, float(item["t"])))
            if not matches:
                raise ValueError(f"missing station temperature history for {hour.isoformat()}")
            temperatures[hour] = max(matches, key=lambda item: item[0])[1]
            hour += timedelta(hours=1)
        return temperatures

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str):
        request_kwargs = {}
        if not self._verify_ssl:
            request_kwargs["ssl"] = False
        async with async_timeout.timeout(10):
            async with session.get(url, **request_kwargs) as response:
                if response.status != 200:
                    raise Exception(f"Error fetching SHMU data: HTTP {response.status} for URL: {url}")
                return await response.json()


def _history_url(hour_utc: datetime) -> str:
    local_hour = _aware_utc(hour_utc).astimezone(SHMU_TIMEZONE)
    return (
        "https://opendata.shmu.sk/meteorology/climate/now/data/"
        f"{local_hour:%Y%m%d}/aws1min%20-%20{local_hour:%Y-%m-%d %H}-00-00.json"
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("history timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
