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
   - Tap `Add hub` to enter the configuration flow (you can add multiple locations).

## Configuration Options

Enter a locality name instead of SHMU numeric IDs. The integration validates it
against SHMU's live location catalogue. If a search or locality maps to several
forecast locations or observation stations, the flow shows a short dependent
selector. `Verify SSL` remains available in both the initial and options flows.

The normal refresh interval is 300 seconds. Existing entries that contain an
older custom `scan_interval` continue to use it, but new entries no longer
expose this implementation detail in the form.

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

Forecast entities read an integration-managed JSON cache. By default, the
integration downloads SHMU ALADIN forecast data during the normal coordinator
update, normalizes station-nearest forecast rows, and writes
`/config/shmu/forecast-cache-<entry_id>.json`.

Legacy entries may retain `forecast_cache_path` as an advanced override and
`forecast_source` as a local file or HTTP(S) helper JSON source. They remain
runtime-compatible but are no longer exposed in the normal configuration or
options UI. Unchanged `source_run_id` values are skipped without rewriting the
cache file, and forecast cache refresh failures are logged without breaking
current station observation sensors.

For helper-based setups, update that cache from cron or a systemd timer with:

```bash
python3 scripts/update_forecast_cache.py helper-output.json /config/shmu/forecast-cache-<entry_id>.json
```

The source can be a local file, `-` for stdin, or an HTTP(S) URL. The script
validates the helper JSON through the integration contract and atomically
replaces the cache file, then prints freshness metadata such as row count, cache
age, model run time, and valid forecast range.

## Troubleshooting

- Re-open the configuration flow and verify the selected locality/station.
- Check the logs for errors if sensors are unavailable.
- For some stations, data or some attributes are not available.
- Sometimes there may be a delay in the publication of data or a longer period with no data published.
