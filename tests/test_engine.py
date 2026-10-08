"""Tests for the surf rules. Run with: python -m unittest discover tests"""

from datetime import date, datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import sys
import unittest

# Loaded by path so the tests do not need Home Assistant installed.
_PATH = Path(__file__).parents[1] / "custom_components" / "surf_conditions" / "engine.py"
_SPEC = importlib.util.spec_from_file_location("surf_conditions_engine", _PATH)
engine = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = engine
_SPEC.loader.exec_module(engine)

UTC = timezone.utc
LISBON = timezone(timedelta(hours=1))  # summer time
DAY = date(2026, 10, 9)
FIRST_LIGHT = datetime(2026, 10, 9, 7, 14, tzinfo=LISBON)
LAST_LIGHT = datetime(2026, 10, 9, 19, 35, tzinfo=LISBON)
LIGHT = (FIRST_LIGHT, LAST_LIGHT)

# Praia do Magoito faces west-north-west, so offshore wind comes from the east-south-east.
MAGOITO = engine.Rules(beach_facing=290)
OFFSHORE, ONSHORE, CROSS_SHORE = 110, 290, 200


def at(hour, minute=0):
    return datetime(2026, 10, 9, hour, minute, tzinfo=LISBON)


def clean_hour(**changes):
    """An hour with everything ideal: 1.2 m at 10 s and a light offshore wind."""
    values = {
        "time": at(10),
        "wave_height": 1.2,
        "period": 10.0,
        "wind_speed": 8.0,
        "wind_gust": 14.0,
        "wind_direction": OFFSHORE,
        "water_temperature": 18.0,
    }
    values.update(changes)
    return engine.Hour(**values)


def rate(tide=engine.TIDE_RISING, light=True, rules=MAGOITO, **changes):
    return engine.assess(clean_hour(**changes), tide, light, rules)


def slot(hour, rating, light=LIGHT):
    """A lit hour with a given rating, for the window tests."""
    return engine.Slot(at(hour), clean_hour(time=at(hour)), None, light, engine.Assessment(rating))


def day(ratings, start=7):
    """Consecutive hours from the 07:00 one, which is the first with light."""
    return [slot(start + index, rating) for index, rating in enumerate(ratings)]


def outlook(ratings, now=at(6), start=7):
    return engine.day_outlook(DAY, day(ratings, start), now, MAGOITO)


class WindTypeTest(unittest.TestCase):
    def test_wind_from_behind_the_beach_is_offshore(self):
        self.assertEqual(engine.wind_type(110, 290), engine.WIND_OFFSHORE)
        self.assertEqual(engine.wind_type(65, 290), engine.WIND_OFFSHORE)
        self.assertEqual(engine.wind_type(155, 290), engine.WIND_OFFSHORE)

    def test_wind_from_the_sea_is_onshore(self):
        self.assertEqual(engine.wind_type(290, 290), engine.WIND_ONSHORE)
        self.assertEqual(engine.wind_type(245, 290), engine.WIND_ONSHORE)

    def test_wind_along_the_beach_is_cross_shore(self):
        self.assertEqual(engine.wind_type(0, 290), engine.WIND_CROSS_SHORE)
        self.assertEqual(engine.wind_type(200, 290), engine.WIND_CROSS_SHORE)

    def test_bearings_wrap_around_north(self):
        self.assertEqual(engine.wind_type(350, 180), engine.WIND_OFFSHORE)
        self.assertEqual(engine.wind_type(10, 180), engine.WIND_OFFSHORE)
        self.assertEqual(engine.wind_type(180, 0), engine.WIND_OFFSHORE)


class RatingTest(unittest.TestCase):
    def test_everything_ideal_is_great(self):
        result = rate()
        self.assertEqual(result.rating, engine.RATING_GREAT)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.wind_type, engine.WIND_OFFSHORE)

    def test_small_waves_are_flat_whatever_else_happens(self):
        result = rate(tide=engine.TIDE_LOW, wave_height=0.3, wind_gust=60, period=3)
        self.assertEqual(result.rating, engine.RATING_FLAT)
        self.assertEqual(result.reason, "Waves of 0.3 m")

    def test_the_wave_range_includes_its_ends(self):
        self.assertEqual(rate(wave_height=0.5).rating, engine.RATING_GREAT)
        self.assertEqual(rate(wave_height=2.0).rating, engine.RATING_GREAT)

    def test_big_waves_are_bad_and_very_big_ones_terrible(self):
        self.assertEqual(rate(wave_height=2.1).rating, engine.RATING_BAD)
        self.assertEqual(rate(wave_height=2.1).reason, "Big waves at 2.1 m")
        self.assertEqual(rate(wave_height=2.5).rating, engine.RATING_BAD)
        self.assertEqual(rate(wave_height=2.6).rating, engine.RATING_TERRIBLE)
        self.assertEqual(rate(wave_height=2.6).reason, "Waves too big at 2.6 m")

    def test_values_are_judged_as_displayed(self):
        self.assertEqual(rate(wave_height=2.04).rating, engine.RATING_GREAT)
        self.assertEqual(rate(wave_height=2.06).rating, engine.RATING_BAD)
        self.assertEqual(rate(wave_height=0.46).rating, engine.RATING_GREAT)
        self.assertEqual(rate(wave_height=0.44).rating, engine.RATING_FLAT)
        self.assertEqual(rate(period=7.96).rating, engine.RATING_GREAT)
        self.assertEqual(rate(wind_direction=ONSHORE, wind_gust=30.2).rating, engine.RATING_GOOD)
        self.assertEqual(rate(wind_direction=ONSHORE, wind_gust=30.6).rating, engine.RATING_BAD)
        self.assertEqual(rate(wind_gust=49.6).rating, engine.RATING_TERRIBLE)

    def test_short_period_is_good_and_very_short_is_bad(self):
        self.assertEqual(rate(period=8).rating, engine.RATING_GREAT)
        self.assertEqual(rate(period=7.65).rating, engine.RATING_GOOD)
        self.assertEqual(rate(period=5).rating, engine.RATING_GOOD)
        self.assertEqual(rate(period=4.9).rating, engine.RATING_BAD)

    def test_wind_that_is_not_offshore_is_good(self):
        result = rate(wind_direction=ONSHORE, wind_speed=12, wind_gust=22)
        self.assertEqual(result.rating, engine.RATING_GOOD)
        self.assertEqual(result.reason, "Onshore wind")
        self.assertEqual(rate(wind_direction=CROSS_SHORE).reason, "Cross-shore wind")

    def test_calm_is_ideal_from_any_direction(self):
        self.assertEqual(rate(wind_direction=ONSHORE, wind_speed=4, wind_gust=9).rating, engine.RATING_GREAT)

    def test_gusts_over_the_limit_are_bad(self):
        self.assertEqual(rate(wind_gust=30).rating, engine.RATING_GREAT)
        self.assertEqual(rate(wind_direction=ONSHORE, wind_gust=30).rating, engine.RATING_GOOD)
        self.assertEqual(rate(wind_direction=ONSHORE, wind_gust=31).rating, engine.RATING_BAD)
        self.assertEqual(rate(wind_direction=ONSHORE, wind_speed=3, wind_gust=31).rating, engine.RATING_BAD)

    def test_strong_offshore_wind_stays_good(self):
        result = rate(wind_gust=38)
        self.assertEqual(result.rating, engine.RATING_GOOD)
        self.assertEqual(result.reason, "Strong offshore wind gusting 38 km/h")
        self.assertEqual(rate(wind_gust=45).rating, engine.RATING_GOOD)
        self.assertEqual(rate(wind_gust=46).rating, engine.RATING_BAD)

    def test_very_strong_gusts_are_terrible(self):
        self.assertEqual(rate(wind_gust=49).rating, engine.RATING_BAD)
        self.assertEqual(rate(wind_gust=49).reason, "Gusts of 49 km/h")
        self.assertEqual(rate(wind_gust=50).rating, engine.RATING_TERRIBLE)

    def test_low_tide_is_bad(self):
        result = rate(tide=engine.TIDE_LOW)
        self.assertEqual(result.rating, engine.RATING_BAD)
        self.assertEqual(result.reason, "Low tide")
        for tide in (engine.TIDE_RISING, engine.TIDE_HIGH, engine.TIDE_FALLING):
            self.assertEqual(rate(tide=tide).rating, engine.RATING_GREAT)

    def test_two_problems_are_terrible(self):
        result = rate(tide=engine.TIDE_LOW, wind_direction=ONSHORE, wind_gust=35)
        self.assertEqual(result.rating, engine.RATING_TERRIBLE)
        self.assertEqual(rate(tide=engine.TIDE_LOW, wave_height=2.3).rating, engine.RATING_TERRIBLE)

    def test_one_problem_with_something_less_than_ideal_is_still_bad(self):
        self.assertEqual(rate(tide=engine.TIDE_LOW, period=6).rating, engine.RATING_BAD)

    def test_reasons_come_worst_first(self):
        result = rate(period=6, wind_gust=55, tide=engine.TIDE_LOW)
        self.assertEqual(result.reason, "Gusts of 55 km/h, low tide, short period of 6 s")

    def test_no_rating_in_the_dark(self):
        result = rate(light=False)
        self.assertEqual(result.rating, engine.RATING_DARK)
        self.assertEqual(result.reason, "")

    def test_no_rating_when_the_forecast_has_gaps(self):
        for gap in ("wave_height", "period", "wind_speed", "wind_gust", "wind_direction"):
            self.assertIsNone(rate(**{gap: None}).rating, gap)
        self.assertIsNone(rate(tide=None).rating)

    def test_the_tide_can_be_ignored(self):
        anywhere = engine.Rules(beach_facing=290, low_tide_hours=0)
        self.assertEqual(rate(tide=engine.TIDE_LOW, rules=anywhere).rating, engine.RATING_GREAT)
        self.assertEqual(rate(tide=None, rules=anywhere).rating, engine.RATING_GREAT)


class TideTest(unittest.TestCase):
    HIGH_WATER = datetime(2026, 10, 9, 2, 15, tzinfo=UTC)
    CYCLE = timedelta(hours=12, minutes=25)

    def setUp(self):
        start = datetime(2026, 10, 8, tzinfo=UTC)
        self.times = [start + timedelta(hours=index) for index in range(72)]
        self.heights = [
            1.5 * math.cos(2 * math.pi * ((moment - self.HIGH_WATER) / self.CYCLE))
            for moment in self.times
        ]
        self.extremes = engine.tide_extremes(self.times, self.heights)

    def test_extremes_fall_between_the_samples(self):
        self.assertEqual(len(self.extremes), 12)
        highs = [extreme for extreme in self.extremes if extreme.high]
        nearest = min(highs, key=lambda extreme: abs(extreme.time - self.HIGH_WATER))
        self.assertLess(abs(nearest.time - self.HIGH_WATER), timedelta(minutes=2))
        self.assertAlmostEqual(nearest.height, 1.5, delta=0.02)

    def test_highs_and_lows_take_turns_half_a_cycle_apart(self):
        for first, second in zip(self.extremes, self.extremes[1:]):
            self.assertNotEqual(first.high, second.high)
            self.assertLess(abs(second.time - first.time - self.CYCLE / 2), timedelta(minutes=4))

    def test_a_flat_top_counts_once(self):
        times = [datetime(2026, 10, 9, hour, tzinfo=UTC) for hour in range(5)]
        extremes = engine.tide_extremes(times, [0.2, 1.0, 1.0, 0.2, -0.5])
        self.assertEqual(len(extremes), 1)
        self.assertTrue(extremes[0].high)
        self.assertEqual(extremes[0].time, datetime(2026, 10, 9, 1, 30, tzinfo=UTC))

    def test_gaps_are_skipped(self):
        times = [datetime(2026, 10, 9, hour, tzinfo=UTC) for hour in range(4)]
        self.assertEqual(engine.tide_extremes(times, [0.2, None, 1.0, 0.2]), [])

    def test_low_tide_lasts_the_given_hours_either_side_of_low_water(self):
        low = next(extreme for extreme in self.extremes if not extreme.high)

        def state(minutes):
            return engine.tide_state(low.time + timedelta(minutes=minutes), self.extremes, 2)

        self.assertEqual(state(0), engine.TIDE_LOW)
        self.assertEqual(state(-119), engine.TIDE_LOW)
        self.assertEqual(state(119), engine.TIDE_LOW)
        self.assertEqual(state(-121), engine.TIDE_FALLING)
        self.assertEqual(state(121), engine.TIDE_RISING)
        self.assertEqual(state(300), engine.TIDE_HIGH)

    def test_low_water_wins_where_the_windows_overlap(self):
        low = next(extreme for extreme in self.extremes if not extreme.high)
        self.assertEqual(engine.tide_state(low.time + timedelta(hours=3.2), self.extremes, 4), engine.TIDE_LOW)

    def test_no_tide_state_past_the_last_extreme(self):
        self.assertIsNone(engine.tide_state(self.times[-1] + timedelta(days=1), self.extremes, 2))

    def test_height_between_samples(self):
        height = engine.tide_height(self.times[3] + timedelta(minutes=30), self.times, self.heights)
        self.assertAlmostEqual(height, (self.heights[3] + self.heights[4]) / 2)
        self.assertIsNone(engine.tide_height(self.times[0] - timedelta(minutes=1), self.times, self.heights))
        self.assertIsNone(engine.tide_height(self.times[-1] + timedelta(minutes=1), self.times, self.heights))


class LightTest(unittest.TestCase):
    MAGOITO = (38.8647, -9.4497)

    def test_sun_height_at_midday(self):
        height = engine.sun_elevation(*self.MAGOITO, datetime(2026, 10, 8, 12, 25, tzinfo=UTC))
        self.assertAlmostEqual(height, 45.15, delta=0.1)

    def test_first_and_last_light_match_civil_twilight(self):
        start = datetime(2026, 10, 8, tzinfo=UTC)
        spans = engine.light_spans(*self.MAGOITO, start, start + timedelta(days=2))
        self.assertEqual(len(spans), 2)
        first, last = spans[0]
        self.assertLess(abs(first - datetime(2026, 10, 8, 6, 13, 33, tzinfo=UTC)), timedelta(minutes=1))
        self.assertLess(abs(last - datetime(2026, 10, 8, 18, 36, 27, tzinfo=UTC)), timedelta(minutes=1))

    def test_light_under_way_is_cut_at_the_edges(self):
        start = datetime(2026, 10, 8, 12, tzinfo=UTC)
        spans = engine.light_spans(*self.MAGOITO, start, start + timedelta(days=1))
        self.assertEqual(spans[0][0], start)
        self.assertEqual(spans[-1][1], start + timedelta(days=1))

    def test_polar_summer_and_winter(self):
        longyearbyen = (78.22, 15.65)
        summer = datetime(2026, 6, 21, tzinfo=UTC)
        winter = datetime(2026, 12, 21, tzinfo=UTC)
        self.assertEqual(
            engine.light_spans(*longyearbyen, summer, summer + timedelta(days=2)),
            [(summer, summer + timedelta(days=2))],
        )
        self.assertEqual(engine.light_spans(*longyearbyen, winter, winter + timedelta(days=2)), [])

    def test_light_at(self):
        self.assertEqual(engine.light_at(at(12), [LIGHT]), LIGHT)
        self.assertEqual(engine.light_at(FIRST_LIGHT, [LIGHT]), LIGHT)
        self.assertIsNone(engine.light_at(LAST_LIGHT, [LIGHT]))
        self.assertIsNone(engine.light_at(at(5), [LIGHT]))


class SlotTest(unittest.TestCase):
    def setUp(self):
        hours = [clean_hour(time=at(hour)) for hour in range(24)]
        extremes = [
            engine.TideExtreme(at(6, 50), 1.1, True),
            engine.TideExtreme(at(13), -1.6, False),
            engine.TideExtreme(at(19, 15), 1.2, True),
        ]
        self.slots = engine.build_slots(hours, extremes, [LIGHT], MAGOITO)

    def ratings(self, first, last):
        return [slot.rating for slot in self.slots[first:last]]

    def test_light_is_judged_at_the_middle_of_the_hour(self):
        self.assertEqual(self.ratings(5, 8), [engine.RATING_DARK, engine.RATING_DARK, engine.RATING_GREAT])
        # Last light is 19:35, after the middle of the 19:00 hour.
        self.assertEqual(self.ratings(18, 21), [engine.RATING_GREAT, engine.RATING_GREAT, engine.RATING_DARK])
        self.assertIsNone(self.slots[6].light)
        self.assertEqual(self.slots[7].light, LIGHT)

    def test_tide_is_judged_at_the_middle_of_the_hour(self):
        # Low water at 13:00 spoils 11:00 to 15:00.
        great, bad = engine.RATING_GREAT, engine.RATING_BAD
        self.assertEqual(self.ratings(10, 16), [great, bad, bad, bad, bad, great])
        self.assertEqual(self.slots[12].tide, engine.TIDE_LOW)

    def test_the_day_has_a_window_either_side_of_low_tide(self):
        result = engine.day_outlook(DAY, self.slots, at(6), MAGOITO)
        self.assertEqual(result.rating, engine.RATING_GREAT)
        self.assertEqual(engine.describe_outlook(result, LISBON), "Great 07:14–11:00 and 15:00–19:35")
        later = engine.day_outlook(DAY, self.slots, at(11, 30), MAGOITO)
        self.assertEqual(engine.describe_outlook(later, LISBON), "Great 15:00–19:35")


class OutlookTest(unittest.TestCase):
    def describe(self, result):
        return engine.describe_outlook(result, LISBON)

    def test_a_great_stretch_inside_a_good_one(self):
        result = outlook(["bad", "good", "good", "great", "great", "good", "good", "bad"])
        self.assertEqual(result.rating, engine.RATING_GREAT)
        self.assertEqual(self.describe(result), "Great 10:00–12:00, surfable 08:00–14:00")
        self.assertEqual(len(result.windows[0].slots), 2)
        self.assertEqual(len(result.surfable[0].slots), 6)

    def test_a_great_stretch_that_is_too_short_makes_a_good_day(self):
        result = outlook(["bad", "good", "great", "good", "bad"])
        self.assertEqual(result.rating, engine.RATING_GOOD)
        self.assertEqual(self.describe(result), "Good 08:00–11:00")

    def test_a_window_that_is_too_short_is_not_reported(self):
        result = outlook(["bad", "great", "bad", "terrible"])
        self.assertEqual(result.rating, engine.RATING_BAD)
        self.assertEqual(result.windows, ())
        self.assertEqual(self.describe(result), "Nothing surfable")

    def test_hours_must_follow_each_other(self):
        apart = [slot(9, "good"), slot(11, "good"), slot(12, "bad")]
        self.assertEqual(engine.day_outlook(DAY, apart, at(6), MAGOITO).rating, engine.RATING_BAD)

    def test_a_flat_day(self):
        result = outlook(["bad", "flat", "flat", "flat", "bad"])
        self.assertEqual(result.rating, engine.RATING_FLAT)
        self.assertEqual(self.describe(result), "Flat 08:00–11:00")
        self.assertEqual(result.surfable, ())

    def test_surfable_beats_flat(self):
        result = outlook(["flat", "flat", "flat", "flat", "good", "good"])
        self.assertEqual(self.describe(result), "Good 11:00–13:00")

    def test_a_terrible_day(self):
        self.assertEqual(outlook(["terrible"] * 6).rating, engine.RATING_TERRIBLE)
        self.assertEqual(outlook(["terrible", "bad", "terrible"]).rating, engine.RATING_BAD)

    def test_every_window_is_listed_in_order(self):
        # The first stretch starts at first light, 07:14, which leaves it under two hours.
        ratings = ["good", "good", "bad", "good", "good", "bad", "good", "good", "good", "bad", "good", "good"]
        self.assertEqual(self.describe(outlook(ratings)), "Good 10:00–12:00, 13:00–16:00 and 17:00–19:00")

    def test_a_great_day_lists_every_surfable_window(self):
        ratings = ["bad", "great", "great", "bad", "good", "good", "bad", "good", "great", "great"]
        self.assertEqual(
            self.describe(outlook(ratings)),
            "Great 08:00–10:00 and 15:00–17:00, surfable 08:00–10:00, 11:00–13:00 and 14:00–17:00",
        )

    def test_windows_are_trimmed_to_the_light(self):
        result = outlook(["good"] * 13)
        self.assertEqual((result.windows[0].start, result.windows[0].end), LIGHT)
        self.assertEqual(self.describe(result), "Good 07:14–19:35")

    def test_trimming_can_make_a_window_too_short(self):
        result = outlook(["bad"] * 11 + ["good", "good"])  # 18:00 to 19:35
        self.assertEqual(result.rating, engine.RATING_BAD)

    def test_a_window_under_way_is_still_reported(self):
        ratings = ["bad", "good", "good", "great", "great", "good", "good", "bad"]
        self.assertEqual(self.describe(outlook(ratings, now=at(11, 30))), "Great 10:00–12:00, surfable 08:00–14:00")
        self.assertEqual(self.describe(outlook(ratings, now=at(12))), "Good 08:00–14:00")
        self.assertEqual(outlook(ratings, now=at(14)).rating, engine.RATING_BAD)

    def test_no_light_left(self):
        result = outlook(["good"] * 13, now=at(19, 40))
        self.assertEqual(result.rating, engine.RATING_DARK)
        self.assertEqual(self.describe(result), "No light left")

    def test_dark_hours_never_join_a_window(self):
        hours = [slot(5, "dark", light=None), slot(6, "dark", light=None), *day(["good"] * 3)]
        result = engine.day_outlook(DAY, hours, at(4), MAGOITO)
        self.assertEqual(len(result.windows[0].slots), 3)

    def test_a_day_without_a_forecast(self):
        result = outlook([None, None, None])
        self.assertIsNone(result.rating)
        self.assertEqual(self.describe(result), "No forecast")


class DescribeTest(unittest.TestCase):
    def test_one_hour_with_the_tide(self):
        hour = engine.build_slots([clean_hour()], [], [LIGHT], engine.Rules(beach_facing=290, low_tide_hours=0))
        self.assertEqual(
            engine.describe_conditions(hour, engine.TIDE_RISING),
            "Waves 1.2 m at 10 s, offshore wind gusting to 14 km/h, rising tide, water 18 °C",
        )

    def test_a_stretch_gives_the_range_and_the_strongest_gust(self):
        hours = [
            clean_hour(time=at(9), wave_height=1.24, period=9.25, wind_gust=12.4, water_temperature=17.6),
            clean_hour(time=at(10), wave_height=1.31, period=10.15, wind_gust=18.2, wind_direction=ONSHORE),
            clean_hour(time=at(11), wave_height=1.42, period=10.15, wind_gust=16.0, wind_direction=ONSHORE),
        ]
        stretch = engine.build_slots(hours, [], [LIGHT], engine.Rules(beach_facing=290, low_tide_hours=0))
        self.assertEqual(
            engine.describe_conditions(stretch),
            "Waves 1.2–1.4 m at 10 s, onshore wind gusting to 18 km/h, water 18 °C",
        )

    def test_gaps_are_left_out(self):
        bare = engine.Slot(at(9), engine.Hour(time=at(9)), None, LIGHT, engine.Assessment(None))
        self.assertEqual(engine.describe_conditions([bare]), "")


if __name__ == "__main__":
    unittest.main()
