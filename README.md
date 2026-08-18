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
   - Create a named SHMU location, then use its add action to attach live
     stations and ALADIN/ECMWF meteograms independently.

## Configuration Options

The top-level entry is a user-named location container and may remain empty.
Each **live station** child selects one official observation station. Each
**meteogram** child independently selects ALADIN or ECMWF plus one official
forecast area. The complete catalogues are searchable in Home Assistant and
submitted IDs are validated again against current SHMU data.

A meteogram may optionally be associated with one live-station child from the
same location, both while it is created and later through its edit action.
When assigned, the forecast weather entity uses that station for current
temperature, pressure, humidity, wind, visibility and observed precipitation.
Without an assignment, those current-observation attributes stay empty and
the forecast remains model-only.

One location can contain several live stations and meteograms, including both
models for the same area. Exact duplicate station or model/area children are
rejected. `Verify SSL` is configured once on the location and inherited by all
of its children. Existing entries are migrated automatically while retaining
their entity and device identities where Home Assistant permits.

The normal refresh interval is 300 seconds. Existing entries that contain an
older custom `scan_interval` continue to use it, but new entries no longer
expose this implementation detail in the form.

Live observations continue to come exclusively from the official SHMU
OpenData JSON directory. The optional station association only supplies those
observations to a forecast entity; it does not add an HTML-page fallback or
change the live-station fetch source.

## Sensors

Each live-station child creates an independent observation device with:

- Temperature (°C)
- Humidity (%)
- Pressure (hPa)
- Wind Speed (m/s)
- Wind Direction (°)
- Global radiation (W/m²)
- Sun duration/min (s)
- Precipitation volume/min (mm)
- Precipitation duration/min (s)

ALADIN and ECMWF meteogram children create separate forecast devices, weather
entities, cache diagnostics and manual refresh buttons. ALADIN also exposes
the meteogram URL and forecast summaries.

[You can find a description of the attributes here](https://opendata.shmu.sk/meteorology/climate/now/metadata/aws1min-metadata.txt)

## Meteogram

The integration provides URL for camera entity for the meteogram image, which updates automatically based on the current time. URL is available as a sensor atribute.

Add to generic camera as static image:
`{{state_attr('sensor.shmu_meteogram_url', 'meteogram_3d_url') }}`
or for 10d meteogram:
`{{state_attr('sensor.shmu_meteogram_url', 'meteogram_10d_url') }}`

## Forecast cache

Each meteogram child owns an independent integration-managed JSON cache. The
default path is
`/config/shmu/<model>-cache-<entry_id>-<subentry_id>.json`, preventing one
model or area from overwriting another. Service calls accept `entry_id` and
`subentry_id`; `subentry_id` is required when a location has several children
of the requested model.

During migration, existing entry-scoped caches are copied into the appropriate
child cache without overwriting newer data; the old files are retained for
rollback. Unchanged `source_run_id` values are skipped without rewriting the
cache, and one forecast-source failure does not break unrelated station or
meteogram children.

For helper-based setups, update that cache from cron or a systemd timer with:

```bash
python3 scripts/update_forecast_cache.py helper-output.json /config/shmu/forecast-cache-<entry_id>.json
```

The source can be a local file, `-` for stdin, or an HTTP(S) URL. The script
validates the helper JSON through the integration contract and atomically
replaces the cache file, then prints freshness metadata such as row count, cache
age, model run time, and valid forecast range.

## Troubleshooting

- Open the location's subentries and verify the selected station, model and
  forecast area. Edit a meteogram child to change or clear its optional live
  station association.
- Check the logs for errors if sensors are unavailable.
- For some stations, data or some attributes are not available.
- Sometimes there may be a delay in the publication of data or a longer period with no data published.
