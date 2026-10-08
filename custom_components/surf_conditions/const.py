"""Constants for Surf Conditions."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "surf_conditions"

# Spot configuration. The rules use the field names of engine.Rules as their keys.
CONF_NAME = "name"
CONF_LOCATION = "location"
CONF_TIDE_OFFSET = "tide_offset"

# Open-Meteo's sea level runs about this many minutes ahead of the Cascais tide table.
DEFAULT_TIDE_OFFSET = 27

ATTRIBUTION = "Weather data by Open-Meteo.com"

UPDATE_INTERVAL = timedelta(minutes=5)  # the tide and the light move on between fetches
FETCH_INTERVAL = timedelta(hours=1)
MAX_FORECAST_AGE = timedelta(hours=6)  # how long a forecast is trusted when fetching fails
OUTLOOK_DAYS = 3  # today, tomorrow and the day after
