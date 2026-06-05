#!/usr/bin/env python3
"""Validate and atomically install SHMU forecast helper JSON.

The Home Assistant integration intentionally consumes a local JSON cache. This
script is the small automation boundary for cron/systemd timers or manual runs:
fetch helper-compatible JSON from a file, stdin, or URL, validate it through the
integration contract, then replace the configured cache file atomically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHMU_MODULE_ROOT = PROJECT_ROOT / "custom_components" / "shmu"
sys.path.insert(0, str(SHMU_MODULE_ROOT))

from forecast import ForecastCache  # noqa: E402


def read_payload(source: str) -> dict:
    """Read helper-compatible JSON from stdin, a local path, or HTTP(S)."""
    if source == "-":
        payload = json.load(sys.stdin)
    elif urlparse(source).scheme in {"http", "https"}:
        request = Request(source, headers={"User-Agent": "ha-shmu-forecast-cache/1.0"})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    else:
        with Path(source).open(encoding="utf-8") as handle:
            payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("helper payload must be a JSON object")
    return payload


def update_cache(source: str, output: str | Path) -> dict:
    """Fetch, validate, save, and return cache freshness metadata."""
    cache = ForecastCache(output)
    cache.save_payload(read_payload(source))
    return cache.info()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate SHMU forecast helper JSON and write a cache file.",
    )
    parser.add_argument(
        "source",
        help="Helper JSON source: local path, '-' for stdin, or HTTP(S) URL.",
    )
    parser.add_argument(
        "output",
        help="Destination cache JSON path configured as forecast_cache_path.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print cache freshness metadata after a successful update.",
    )
    args = parser.parse_args(argv)

    info = update_cache(args.source, args.output)
    if not args.quiet:
        json.dump(info, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
