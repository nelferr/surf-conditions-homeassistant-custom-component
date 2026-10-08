"""Coordinator: fetches the forecast and works out the rating, tides and windows."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, time, timedelta, tzinfo
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Forecast, OpenMeteoError, async_fetch
from .const import (
    CONF_LOCATION,
    CONF_TIDE_OFFSET,
    DEFAULT_TIDE_OFFSET,
    DOMAIN,
    FETCH_INTERVAL,
    MAX_FORECAST_AGE,
    OUTLOOK_DAYS,
    UPDATE_INTERVAL,
)
from .engine import (
    HOUR,
    Outlook,
    Rules,
    Slot,
    TideExtreme,
    assess,
    build_slots,
    day_outlook,
    light_at,
    light_spans,
    tide_extremes,
    tide_height,
    tide_state,
)

_LOGGER = logging.getLogger(__name__)

type SurfConditionsConfigEntry = ConfigEntry[SurfConditionsCoordinator]


@dataclass(frozen=True)
class SpotData:
    """What the entities show for one spot."""

    zone: tzinfo
    now: Slot | None  # the current hour, rated for this very moment
    tide_height: float | None
    next_high: TideExtreme | None
    next_low: TideExtreme | None
    first_light: datetime | None  # of the light under way, or of the next one at night
    last_light: datetime | None
    outlooks: tuple[Outlook, ...]  # today, tomorrow, the day after
    slots: tuple[Slot, ...]  # every hour of those days


class SurfConditionsCoordinator(DataUpdateCoordinator[SpotData]):
    """Keeps one spot's forecast and what the rules make of it."""

    config_entry: SurfConditionsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SurfConditionsConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        conf = {**entry.data, **entry.options}
        self.latitude = float(conf[CONF_LOCATION][CONF_LATITUDE])
        self.longitude = float(conf[CONF_LOCATION][CONF_LONGITUDE])
        self.rules = Rules(
            **{field.name: float(conf.get(field.name, field.default)) for field in fields(Rules)}
        )
        self.tide_offset = timedelta(minutes=float(conf.get(CONF_TIDE_OFFSET, DEFAULT_TIDE_OFFSET)))
        self._forecast: Forecast | None = None
        self._fetched: datetime | None = None
        self._zone: tzinfo = dt_util.DEFAULT_TIME_ZONE

    async def _async_update_data(self) -> SpotData:
        """Fetch a new forecast when the last one is an hour old, then apply the rules."""
        now = dt_util.utcnow()
        if self._fetched is None or now - self._fetched >= FETCH_INTERVAL:
            try:
                forecast = await async_fetch(
                    async_get_clientsession(self.hass), self.latitude, self.longitude
                )
            except OpenMeteoError as err:
                if self._fetched is None or now - self._fetched > MAX_FORECAST_AGE:
                    raise UpdateFailed(str(err)) from err
                _LOGGER.debug("Keeping the last forecast: %s", err)
            else:
                self._forecast = forecast
                self._fetched = now
                self._zone = await self._async_zone(forecast.time_zone)
        return self._compute(now)

    async def _async_zone(self, name: str | None) -> tzinfo:
        """The spot's time zone, so days and window times are local to the beach."""
        zone = None
        if name:
            zone = await self.hass.async_add_executor_job(dt_util.get_time_zone, name)
        return zone or dt_util.DEFAULT_TIME_ZONE

    def _compute(self, now: datetime) -> SpotData:
        hours = self._forecast.hours
        zone = self._zone
        rules = self.rules
        today = now.astimezone(zone).date()
        midnight = datetime.combine(today, time.min, zone)
        spans = light_spans(
            self.latitude,
            self.longitude,
            midnight - timedelta(days=1),
            midnight + timedelta(days=OUTLOOK_DAYS + 1),
        )
        tide_times = [hour.time + self.tide_offset for hour in hours]
        sea_levels = [hour.sea_level for hour in hours]
        extremes = tide_extremes(tide_times, sea_levels)

        days = [today + timedelta(days=ahead) for ahead in range(OUTLOOK_DAYS)]
        slots = [
            slot
            for slot in build_slots(hours, extremes, spans, rules)
            if slot.start.astimezone(zone).date() in days
        ]
        outlooks = tuple(
            day_outlook(
                day, [s for s in slots if s.start.astimezone(zone).date() == day], now, rules
            )
            for day in days
        )

        current = None
        hour = next((h for h in hours if h.time <= now < h.time + HOUR), None)
        if hour is not None:
            tide = tide_state(now, extremes, rules.low_tide_hours)
            light = light_at(now, spans)
            verdict = assess(hour, tide, light is not None, rules)
            current = Slot(hour.time, hour, tide, light, verdict)

        # First light keeps today's time until last light. Changing it the moment it passes
        # could reschedule an automation waiting for that very moment before it has run.
        first_light, last_light = next((span for span in spans if span[1] > now), (None, None))

        return SpotData(
            zone=zone,
            now=current,
            tide_height=tide_height(now, tide_times, sea_levels),
            next_high=next((e for e in extremes if e.high and e.time > now), None),
            next_low=next((e for e in extremes if not e.high and e.time > now), None),
            first_light=first_light,
            last_light=last_light,
            outlooks=outlooks,
            slots=tuple(slots),
        )
