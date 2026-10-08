"""Surf rules for one spot: rating, tides, light and windows. No Home Assistant imports."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
import math

RATING_GREAT = "great"
RATING_GOOD = "good"
RATING_FLAT = "flat"
RATING_BAD = "bad"
RATING_TERRIBLE = "terrible"
RATING_DARK = "dark"
RATINGS = [RATING_GREAT, RATING_GOOD, RATING_FLAT, RATING_BAD, RATING_TERRIBLE, RATING_DARK]

WIND_OFFSHORE = "offshore"
WIND_CROSS_SHORE = "cross_shore"
WIND_ONSHORE = "onshore"
WIND_TYPES = [WIND_OFFSHORE, WIND_CROSS_SHORE, WIND_ONSHORE]

TIDE_LOW = "low"
TIDE_RISING = "rising"
TIDE_HIGH = "high"
TIDE_FALLING = "falling"
TIDE_STATES = [TIDE_LOW, TIDE_RISING, TIDE_HIGH, TIDE_FALLING]

HOUR = timedelta(hours=1)
TWILIGHT = -6.0  # the sun's height at first and last light (civil twilight)

# How much one factor holds a session back
_IDEAL, _FAIR, _PROBLEM, _TERRIBLE = range(4)

_WIND_WORDS = {
    WIND_OFFSHORE: "offshore",
    WIND_CROSS_SHORE: "cross-shore",
    WIND_ONSHORE: "onshore",
}
_TIDE_WORDS = {
    TIDE_LOW: "low tide",
    TIDE_RISING: "rising tide",
    TIDE_HIGH: "high tide",
    TIDE_FALLING: "falling tide",
}
_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)

type Light = tuple[datetime, datetime]  # first light, last light


@dataclass(frozen=True)
class Rules:
    """One spot's thresholds: heights in metres, periods in seconds, wind in km/h."""

    beach_facing: float = 270.0  # compass bearing looking from the sand out to sea
    wave_min: float = 0.5  # smaller than this is flat
    wave_max: float = 2.0  # bigger than this is a problem
    wave_terrible: float = 2.5  # bigger than this is terrible
    period_ideal: float = 8.0  # shorter than this is good at best
    period_min: float = 5.0  # shorter than this is a problem
    gust_max: float = 30.0  # stronger gusts are a problem
    offshore_gust_max: float = 45.0  # except offshore, which stays good up to here
    gust_terrible: float = 50.0  # gusts from here up are terrible
    calm_wind: float = 5.0  # average wind below this is ideal from any direction
    low_tide_hours: float = 2.0  # hours either side of low water to avoid; 0 ignores the tide
    min_window_hours: float = 2.0  # shortest window worth reporting


@dataclass(frozen=True)
class Hour:
    """The forecast for the hour starting at time."""

    time: datetime
    wave_height: float | None = None
    period: float | None = None  # peak period of the dominant waves
    wind_speed: float | None = None
    wind_gust: float | None = None
    wind_direction: float | None = None  # where the wind comes from
    water_temperature: float | None = None
    sea_level: float | None = None


@dataclass(frozen=True)
class Assessment:
    """A rating and what holds it back. The rating is None when the forecast has gaps."""

    rating: str | None
    reasons: tuple[str, ...] = ()
    wind_type: str | None = None

    @property
    def reason(self) -> str:
        """The reasons as one line, worst first."""
        return _sentence(self.reasons)


@dataclass(frozen=True)
class TideExtreme:
    """A high or low water."""

    time: datetime
    height: float
    high: bool


@dataclass(frozen=True)
class Slot:
    """One forecast hour with its tide, light and rating worked out."""

    start: datetime
    hour: Hour
    tide: str | None
    light: Light | None  # the stretch of light this hour falls in, None when dark
    assessment: Assessment

    @property
    def end(self) -> datetime:
        """When the hour is over."""
        return self.start + HOUR

    @property
    def rating(self) -> str | None:
        """The hour's rating."""
        return self.assessment.rating


@dataclass(frozen=True)
class Window:
    """A stretch of consecutive hours, trimmed to first and last light."""

    start: datetime
    end: datetime
    slots: tuple[Slot, ...]


@dataclass(frozen=True)
class Outlook:
    """The best a day still has to offer."""

    day: date
    rating: str | None
    windows: tuple[Window, ...] = ()  # the stretches that earn the rating, in order
    surfable: tuple[Window, ...] = ()  # the good-or-better stretches, in order


def wind_type(wind_direction: float, beach_facing: float) -> str:
    """Offshore wind blows from the land out to sea, so it comes from behind the beach."""
    offshore_from = beach_facing + 180
    angle = abs((wind_direction - offshore_from + 180) % 360 - 180)
    if angle <= 45:
        return WIND_OFFSHORE
    if angle >= 135:
        return WIND_ONSHORE
    return WIND_CROSS_SHORE


def assess(hour: Hour, tide: str | None, light: bool, rules: Rules) -> Assessment:
    """Rate one hour.

    Small waves are flat whatever else happens. Otherwise one problem makes it bad, two make
    it terrible, and with no problems it is good, or great when every factor is ideal.

    Values are judged as they are displayed, heights and periods to one decimal and wind to
    whole km/h, so a gust of 30.2 does not break a limit of 30.
    """
    wind = None
    if hour.wind_direction is not None:
        wind = wind_type(hour.wind_direction, rules.beach_facing)
    if not light:
        return Assessment(RATING_DARK, (), wind)
    if hour.wave_height is None:
        return Assessment(None, (), wind)
    height = round(hour.wave_height, 1)
    if height < rules.wave_min:
        return Assessment(RATING_FLAT, (f"waves of {_number(height)} m",), wind)

    use_tide = rules.low_tide_hours > 0
    if (
        hour.period is None
        or hour.wind_speed is None
        or hour.wind_gust is None
        or wind is None
        or (use_tide and tide is None)
    ):
        return Assessment(None, (), wind)

    factors = [
        _rate_waves(height, rules),
        _rate_period(round(hour.period, 1), rules),
        _rate_wind(round(hour.wind_speed), round(hour.wind_gust), wind, rules),
    ]
    if use_tide and tide == TIDE_LOW:
        factors.append((_PROBLEM, "low tide"))

    worst = max(level for level, _ in factors)
    problems = sum(level == _PROBLEM for level, _ in factors)
    if worst == _TERRIBLE or problems >= 2:
        rating = RATING_TERRIBLE
    elif problems == 1:
        rating = RATING_BAD
    elif worst == _FAIR:
        rating = RATING_GOOD
    else:
        rating = RATING_GREAT
    held_back = sorted((f for f in factors if f[0] != _IDEAL), key=lambda f: -f[0])
    return Assessment(rating, tuple(reason for _, reason in held_back), wind)


def _rate_waves(height: float, rules: Rules) -> tuple[int, str | None]:
    if height > rules.wave_terrible:
        return _TERRIBLE, f"waves too big at {_number(height)} m"
    if height > rules.wave_max:
        return _PROBLEM, f"big waves at {_number(height)} m"
    return _IDEAL, None


def _rate_period(period: float, rules: Rules) -> tuple[int, str | None]:
    if period < rules.period_min:
        return _PROBLEM, f"very short period of {_number(period)} s"
    if period < rules.period_ideal:
        return _FAIR, f"short period of {_number(period)} s"
    return _IDEAL, None


def _rate_wind(speed: float, gust: float, kind: str, rules: Rules) -> tuple[int, str | None]:
    if gust >= rules.gust_terrible:
        return _TERRIBLE, f"gusts of {_number(gust)} km/h"
    if gust > rules.gust_max:
        if kind == WIND_OFFSHORE and gust <= rules.offshore_gust_max:
            return _FAIR, f"strong offshore wind gusting {_number(gust)} km/h"
        return _PROBLEM, f"gusts of {_number(gust)} km/h"
    if speed < rules.calm_wind or kind == WIND_OFFSHORE:
        return _IDEAL, None
    return _FAIR, f"{_WIND_WORDS[kind]} wind"


def tide_extremes(
    times: Sequence[datetime], heights: Sequence[float | None]
) -> list[TideExtreme]:
    """Find high and low water in an evenly spaced sea-level series.

    A parabola through each turning point and its two neighbours places the extreme between
    the samples.
    """
    extremes: list[TideExtreme] = []
    for index in range(1, len(heights) - 1):
        before, here, after = heights[index - 1], heights[index], heights[index + 1]
        if before is None or here is None or after is None:
            continue
        high = here >= before and here > after
        low = here <= before and here < after
        if not (high or low):
            continue
        curve = before - 2 * here + after
        shift = 0.5 * (before - after) / curve if curve else 0.0
        step = times[index + 1] - times[index]
        extremes.append(
            TideExtreme(times[index] + shift * step, here - 0.25 * (before - after) * shift, high)
        )
    return extremes


def tide_height(
    at: datetime, times: Sequence[datetime], heights: Sequence[float | None]
) -> float | None:
    """Sea level at a moment, on a straight line between the two nearest samples."""
    index = bisect_right(times, at) - 1
    if index < 0 or index >= len(times) - 1:
        return None
    before, after = heights[index], heights[index + 1]
    if before is None or after is None:
        return None
    share = (at - times[index]) / (times[index + 1] - times[index])
    return before + (after - before) * share


def tide_state(at: datetime, extremes: Sequence[TideExtreme], hours: float) -> str | None:
    """Low or high within the given hours of an extreme, otherwise rising or falling."""
    window = timedelta(hours=hours)
    for high in (False, True):  # low water wins where the two overlap
        if any(e.high is high and abs(e.time - at) <= window for e in extremes):
            return TIDE_HIGH if high else TIDE_LOW
    following = next((e for e in extremes if e.time > at), None)
    if following is None:
        return None
    return TIDE_RISING if following.high else TIDE_FALLING


def sun_elevation(latitude: float, longitude: float, at: datetime) -> float:
    """Height of the sun above the horizon in degrees.

    Uses the Astronomical Almanac's short formulas, good to about 0.01 degrees until 2050.
    """
    days = (at - _J2000).total_seconds() / 86400
    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360)
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360)
    ecliptic = mean_longitude + math.radians(
        1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly)
    )
    tilt = math.radians(23.439 - 0.0000004 * days)
    right_ascension = math.atan2(math.cos(tilt) * math.sin(ecliptic), math.cos(ecliptic))
    declination = math.asin(math.sin(tilt) * math.sin(ecliptic))
    sidereal = math.radians((280.46061837 + 360.98564736629 * days + longitude) % 360)
    hour_angle = sidereal - right_ascension
    phi = math.radians(latitude)
    return math.degrees(
        math.asin(
            math.sin(phi) * math.sin(declination)
            + math.cos(phi) * math.cos(declination) * math.cos(hour_angle)
        )
    )


def light_spans(latitude: float, longitude: float, start: datetime, end: datetime) -> list[Light]:
    """The stretches from first to last light between start and end.

    A stretch already under way at start, or still going at end, is cut off there.
    """

    def lit(at: datetime) -> bool:
        return sun_elevation(latitude, longitude, at) > TWILIGHT

    spans: list[Light] = []
    step = timedelta(minutes=10)
    at = start
    light = lit(at)
    opened = start
    while at < end:
        following = min(at + step, end)
        if lit(following) != light:
            # Close in on the moment the light changes.
            before, after = at, following
            while after - before > timedelta(seconds=1):
                middle = before + (after - before) / 2
                if lit(middle) == light:
                    before = middle
                else:
                    after = middle
            if light:
                spans.append((opened, after))
            opened = after
            light = not light
        at = following
    if light:
        spans.append((opened, end))
    return spans


def light_at(at: datetime, spans: Sequence[Light]) -> Light | None:
    """The stretch of light a moment falls in, or None when it is dark."""
    return next((span for span in spans if span[0] <= at < span[1]), None)


def build_slots(
    hours: Sequence[Hour],
    extremes: Sequence[TideExtreme],
    spans: Sequence[Light],
    rules: Rules,
) -> list[Slot]:
    """Rate every hour, judging tide and light at the middle of the hour."""
    slots = []
    for hour in hours:
        middle = hour.time + HOUR / 2
        tide = tide_state(middle, extremes, rules.low_tide_hours)
        light = light_at(middle, spans)
        slots.append(
            Slot(hour.time, hour, tide, light, assess(hour, tide, light is not None, rules))
        )
    return slots


def day_outlook(day: date, slots: Sequence[Slot], now: datetime, rules: Rules) -> Outlook:
    """Find the windows still open among one day's hours.

    A window counts until it ends, so one already in progress is still reported. A day is
    great when it has a long enough great stretch, good when it has a long enough stretch of
    good or better, and flat when it has a long enough flat stretch.
    """
    if not slots:
        return Outlook(day, None)
    lit = [slot for slot in slots if slot.light is not None]
    great = _windows(lit, {RATING_GREAT}, now, rules)
    surfable = _windows(lit, {RATING_GREAT, RATING_GOOD}, now, rules)
    if great:
        return Outlook(day, RATING_GREAT, great, surfable)
    if surfable:
        return Outlook(day, RATING_GOOD, surfable, surfable)
    flat = _windows(lit, {RATING_FLAT}, now, rules)
    if flat:
        return Outlook(day, RATING_FLAT, flat)

    left = [slot.rating for slot in lit if min(slot.end, slot.light[1]) > now]
    if not left:
        return Outlook(day, RATING_DARK)
    if all(rating is None for rating in left):
        return Outlook(day, None)
    if all(rating in (RATING_TERRIBLE, None) for rating in left):
        return Outlook(day, RATING_TERRIBLE)
    return Outlook(day, RATING_BAD)


def _windows(
    lit: Sequence[Slot], ratings: set[str], now: datetime, rules: Rules
) -> tuple[Window, ...]:
    """Stretches of consecutive lit hours with one of the ratings, long enough and not over."""
    shortest = timedelta(hours=rules.min_window_hours)
    windows: list[Window] = []
    run: list[Slot] = []
    for slot in [*lit, None]:
        wanted = slot is not None and slot.rating in ratings
        if wanted and (not run or slot.start == run[-1].end):
            run.append(slot)
            continue
        if run:
            start = max(run[0].start, run[0].light[0])
            end = min(run[-1].end, run[-1].light[1])
            if end > now and end - start >= shortest:
                windows.append(Window(start, end, tuple(run)))
        run = [slot] if wanted else []
    return tuple(windows)


def describe_outlook(outlook: Outlook, zone: tzinfo) -> str:
    """Say a day's outlook in one line, like "Great 10:00–12:00, surfable 08:00–14:00"."""
    if outlook.rating is None:
        return "No forecast"
    if outlook.rating == RATING_DARK:
        return "No light left"
    if not outlook.windows:
        return "Nothing surfable"
    best = _spans(outlook.windows, zone)
    text = f"{outlook.rating.capitalize()} {best}"
    around = _spans(outlook.surfable, zone)
    if around and around != best:
        text += f", surfable {around}"
    return text


def describe_conditions(slots: Sequence[Slot], tide: str | None = None) -> str:
    """Sum up the waves, wind and water over some hours in one line."""
    parts = []
    heights = [s.hour.wave_height for s in slots if s.hour.wave_height is not None]
    if heights:
        smallest, biggest = _number(min(heights)), _number(max(heights))
        size = smallest if smallest == biggest else f"{smallest}–{biggest}"
        text = f"waves {size} m"
        periods = [s.hour.period for s in slots if s.hour.period is not None]
        if periods:
            text += f" at {_number(sum(periods) / len(periods), 0)} s"
        parts.append(text)
    gusts = [s.hour.wind_gust for s in slots if s.hour.wind_gust is not None]
    kinds = [s.assessment.wind_type for s in slots if s.assessment.wind_type is not None]
    if gusts and kinds:
        kind = max(WIND_TYPES, key=kinds.count)
        parts.append(f"{_WIND_WORDS[kind]} wind gusting to {_number(max(gusts), 0)} km/h")
    if tide is not None:
        parts.append(_TIDE_WORDS[tide])
    water = [s.hour.water_temperature for s in slots if s.hour.water_temperature is not None]
    if water:
        parts.append(f"water {_number(sum(water) / len(water), 0)} °C")
    return _sentence(parts)


def _spans(windows: Sequence[Window], zone: tzinfo) -> str:
    """Window times in a row, like "07:14–11:00 and 15:00–19:35"."""
    spans = [f"{w.start.astimezone(zone):%H:%M}–{w.end.astimezone(zone):%H:%M}" for w in windows]
    return " and ".join([", ".join(spans[:-1]), spans[-1]] if len(spans) > 1 else spans)


def _number(value: float, digits: int = 1) -> str:
    """A number without trailing zeros: 2.0 reads as 2."""
    return f"{round(value, digits):g}"


def _sentence(parts: Sequence[str]) -> str:
    text = ", ".join(parts)
    return text[:1].upper() + text[1:]
