# ha-shmu
# SHMU Integration for Home Assistant

This integration fetches meteorological data from the [Slovenský hydrometeorologický ústav (SHMU)](https://www.shmu.sk/) and provides sensors for temperature, humidity, pressure, wind speed, and wind direction. It also generates a meteogram image URL.
This is only integration, all data is provided by [SHMU Open Data](https://opendata.shmu.sk/).

## Fork
This is a fork of `https://github.com/3DRIK/ha-shmu`. This fork adds forecast entities.

## Installation

1. **Add this repository to HACS**:
   - Go to HACS > Integrations > Custom Repositories.
   - Add `https://github.com/jezek/ha-shmu` as a custom repository.
   - Install the "SHMU" integration.

2. **Configure the integration**:
   - Go to Configuration > Integrations > Add Integration > SHMU.
   - Tap `Add hub` to enter cobfiguration flow (you can add multiple stations)

## Configuration Options

| Option         | Description                                                                 |
|----------------|-----------------------------------------------------------------------------|
| Station ID     | ID of the SHMU meteorological station (e.g., `11813` for Bratislava).      |
| Meteogram ID   | ID of the SHMU meteogram loaction (e.g., `32737` for Bratislava or `none` for no meteogram). |
| Scan Interval  | How often (in seconds) the data should be updated (default: 300 seconds).  |
| Verify SSL     | Verifying SHMU API SSL (recommended).                                      |

- You can find your nearest station at [SHMU Stations](https://www.shmu.sk/sk//?page=1&id=meteo_apocasie_sk) with ID in URL.
- You can find Meteogram locations at [SHMU Meteograms](https://www.shmu.sk/sk/?page=769) with ID in URL.

## Sensors

The integration creates device with the following sensors:

- Temperature (°C)
- Humidity (%)
- Pressure (hPa)
- Wind Speed (m/s)
- Wind Direction (°)
- Global radiation (W/m²)
- Sun duration/min (s)
- Precipitation volume/min (mm)
- Precipitation duration/min (s)
- Meteogram url (containing meteogram image url for 3 and 10 days in attributes)

[You can find a description of the attributes here](https://opendata.shmu.sk/meteorology/climate/now/metadata/aws1min-metadata.txt)

## Meteogram

The integration provides URL for camera entity for the meteogram image, which updates automatically based on the current time. URL is available as a sensor atribute.

Add to generic camera as static image:
`{{state_attr('sensor.shmu_meteogram_url', 'meteogram_3d_url') }}`
or for 10d meteogram:
`{{state_attr('sensor.shmu_meteogram_url', 'meteogram_10d_url') }}`

## Forecast cache

Forecast entities read a local helper JSON cache. By default, the integration
uses `/config/shmu/forecast-cache-<entry_id>.json`; `forecast_cache_path` remains
available as an override.
`forecast_source` can point at a local file or HTTP(S) URL containing
helper-compatible JSON for runtime refresh support.
When `forecast_source` is configured, the integration refreshes the cache during
the normal SHMU coordinator update. Unchanged `source_run_id` values are skipped
without rewriting the cache file, and forecast cache refresh failures are logged
without breaking current station observation sensors.

Update that cache from cron or a systemd timer with:

```bash
python3 scripts/update_forecast_cache.py helper-output.json /config/shmu/forecast-cache-<entry_id>.json
```

The source can be a local file, `-` for stdin, or an HTTP(S) URL. The script
validates the helper JSON through the integration contract and atomically
replaces the cache file, then prints freshness metadata such as row count, cache
age, model run time, and valid forecast range.

## Troubleshooting

- Ensure your station ID is correct.
- Check the logs for errors if sensors are unavailable.
- For some stations, data or some attributes are not available.
- Sometimes there may be a delay in the publication of data or a longer period with no data published.
