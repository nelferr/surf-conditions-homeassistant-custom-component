"""Open-Meteo client: waves and sea level from the Marine API, wind from the Forecast API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .engine import Hour

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_MARINE = (
    "wave_height",
    "wave_period",
    "swell_wave_height",
    "swell_wave_period",
    "swell_wave_peak_period",
    "wind_wave_height",
    "wind_wave_period",
    "wind_wave_peak_period",
    "sea_surface_temperature",
    "sea_level_height_msl",
)
_WIND = ("wind_speed_10m", "wind_gusts_10m", "wind_direction_10m")
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_HOUR = 3600


class OpenMeteoError(Exception):
    """Open-Meteo could not be reached or sent something unusable."""


class OpenMeteoRefused(OpenMeteoError):
    """Open-Meteo answered that it has nothing for this request."""


@dataclass(frozen=True)
class Forecast:
    """Hourly rows for one spot, oldest first, and the name of the spot's time zone."""

    hours: list[Hour]
    time_zone: str | None


async def async_fetch(
    session: aiohttp.ClientSession, latitude: float, longitude: float
) -> Forecast:
    """Fetch yesterday to three days ahead. Yesterday is needed to find the last tide."""
    common = {
        "latitude": latitude,
        "longitude": longitude,
        "past_days": 1,
        "forecast_days": 4,
        "timeformat": "unixtime",
        "timezone": "auto",
    }
    sea = {**common, "hourly": ",".join(_MARINE), "cell_selection": "sea"}
    air = {**common, "hourly": ",".join(_WIND), "wind_speed_unit": "kmh"}
    marine, wind = await asyncio.gather(
        _get(session, MARINE_URL, sea), _get(session, FORECAST_URL, air)
    )
    return parse(marine, wind)


async def _get(session: aiohttp.ClientSession, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        async with session.get(url, params=params, timeout=_TIMEOUT) as response:
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise OpenMeteoError(f"Request to {url} failed: {err}") from err
    if isinstance(data, dict) and data.get("error"):
        raise OpenMeteoRefused(str(data.get("reason") or f"{url} refused the request"))
    if not isinstance(data, dict) or "hourly" not in data:
        raise OpenMeteoError(f"Unexpected answer from {url}")
    return data


def parse(marine: dict[str, Any], wind: dict[str, Any]) -> Forecast:
    """Join the two answers into one row per hour."""
    sea = _rows(marine["hourly"])
    air = _rows(wind["hourly"])
    hours = []
    for stamp in sorted(sea):
        row = sea[stamp]
        breeze = air.get(stamp, {})
        # Open-Meteo stamps a gust with the end of the hour it was the strongest in.
        gust = air.get(stamp + _HOUR, {}).get("wind_gusts_10m")
        if gust is None:
            gust = breeze.get("wind_gusts_10m")
        hours.append(
            Hour(
                time=datetime.fromtimestamp(stamp, timezone.utc),
                wave_height=row.get("wave_height"),
                period=_dominant_period(row),
                wind_speed=breeze.get("wind_speed_10m"),
                wind_gust=gust,
                wind_direction=breeze.get("wind_direction_10m"),
                water_temperature=row.get("sea_surface_temperature"),
                sea_level=row.get("sea_level_height_msl"),
            )
        )
    return Forecast(hours, marine.get("timezone"))


def _rows(hourly: dict[str, list[Any]]) -> dict[int, dict[str, Any]]:
    """Turn Open-Meteo's one-list-per-value layout into one dict per timestamp."""
    names = [name for name in hourly if name != "time"]
    return {
        stamp: {name: hourly[name][index] for name in names}
        for index, stamp in enumerate(hourly["time"])
    }


def _dominant_period(row: dict[str, Any]) -> float | None:
    """Peak period of whichever is bigger, the swell or the local wind waves.

    Not every wave model reports peak periods, so mean periods stand in when they are missing.
    """
    swell = row.get("swell_wave_peak_period") or row.get("swell_wave_period")
    chop = row.get("wind_wave_peak_period") or row.get("wind_wave_period")
    chop_is_bigger = (row.get("wind_wave_height") or 0) > (row.get("swell_wave_height") or 0)
    if chop and (not swell or chop_is_bigger):
        return chop
    return swell or row.get("wave_period")
