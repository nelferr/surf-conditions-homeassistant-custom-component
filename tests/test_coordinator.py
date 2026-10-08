"""Tests for the coordinator's update loop, run against stubbed Home Assistant modules."""

import asyncio
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

import ha_stubs  # noqa: E402

ha_stubs.install()

from custom_components.surf_conditions import api, engine  # noqa: E402
from custom_components.surf_conditions import coordinator as module  # noqa: E402
from custom_components.surf_conditions.coordinator import SurfConditionsCoordinator  # noqa: E402

Clock = ha_stubs.Clock
UTC = timezone.utc
LOCAL = ha_stubs.LOCAL
MINUTE = timedelta(minutes=1)

SPOT = {
    "name": "Magoito",
    "location": {"latitude": 38.8647, "longitude": -9.4497},
    "beach_facing": 290,
}
CYCLE = timedelta(hours=12, minutes=25)
# High water as Open-Meteo reports it, 27 minutes early. The real one is at 14:27 local time,
# with low water half a cycle either side: 08:14 and 20:39.
REPORTED_HIGH = datetime(2026, 10, 9, 13, 0, tzinfo=UTC)
HIGH = REPORTED_HIGH + timedelta(minutes=27)


def forecast(zone="Europe/Lisbon", rows=120, **changes):
    """Ideal surf for five days from midnight on the 8th, local time, with a regular tide."""
    start = datetime(2026, 10, 7, 23, tzinfo=UTC)
    hours = []
    for index in range(rows):
        moment = start + timedelta(hours=index)
        values = {
            "time": moment,
            "wave_height": 1.2,
            "period": 10.0,
            "wind_speed": 8.0,
            "wind_gust": 14.0,
            "wind_direction": 110.0,
            "water_temperature": 18.0,
            "sea_level": 1.5 * math.cos(2 * math.pi * ((moment - REPORTED_HIGH) / CYCLE)),
        }
        values.update(changes)
        hours.append(engine.Hour(**values))
    return api.Forecast(hours, zone)


def local(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=LOCAL)


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        Clock.set_local(9, 10, 30)
        self.fetches = 0
        self.failure = None
        self.forecast = forecast()

        async def fetch(session, latitude, longitude):
            self.fetches += 1
            self.asked_for = (latitude, longitude)
            if self.failure is not None:
                raise self.failure
            return self.forecast

        self.addCleanup(setattr, module, "async_fetch", module.async_fetch)
        module.async_fetch = fetch

    def make(self, **options):
        entry = SimpleNamespace(title="Magoito", data=SPOT, options=options)
        return SurfConditionsCoordinator(ha_stubs.FakeHass(), entry)

    def refresh(self, coordinator):
        asyncio.run(coordinator.async_refresh())
        return coordinator.data

    def summaries(self, data):
        return [engine.describe_outlook(outlook, data.zone) for outlook in data.outlooks]

    def test_first_refresh(self):
        data = self.refresh(self.make())
        self.assertEqual(self.asked_for, (38.8647, -9.4497))
        self.assertIs(data.zone, LOCAL)
        self.assertEqual(data.now.rating, engine.RATING_GREAT)
        self.assertEqual(data.now.start, local(9, 10))
        self.assertEqual(data.now.tide, engine.TIDE_RISING)
        self.assertEqual(data.now.assessment.wind_type, engine.WIND_OFFSHORE)

    def test_tides_are_shifted_by_the_offset(self):
        data = self.refresh(self.make())
        self.assertTrue(data.next_high.high)
        self.assertLess(abs(data.next_high.time - HIGH), 2 * MINUTE)
        self.assertAlmostEqual(data.next_high.height, 1.5, delta=0.02)
        self.assertLess(abs(data.next_low.time - (HIGH + CYCLE / 2)), 2 * MINUTE)
        self.assertTrue(-1.5 < data.tide_height < 0)

        unshifted = self.refresh(self.make(tide_offset=0))
        self.assertLess(abs(unshifted.next_high.time - REPORTED_HIGH), 2 * MINUTE)

    def test_light_is_todays_until_it_is_over(self):
        coordinator = self.make()
        for hour in (3, 10, 19):
            Clock.set_local(9, hour)
            data = self.refresh(coordinator)
            self.assertLess(abs(data.first_light - local(9, 7, 14)), MINUTE)
            self.assertLess(abs(data.last_light - local(9, 19, 35)), MINUTE)
        Clock.set_local(9, 19, 40)
        data = self.refresh(coordinator)
        self.assertLess(abs(data.first_light - local(10, 7, 15)), MINUTE)
        self.assertLess(abs(data.last_light - local(10, 19, 33)), MINUTE)

    def test_outlooks_cover_three_local_days(self):
        data = self.refresh(self.make())
        self.assertEqual([outlook.day.day for outlook in data.outlooks], [9, 10, 11])
        self.assertEqual(len(data.slots), 72)
        self.assertEqual(data.slots[0].start, local(9, 0))
        self.assertEqual(data.slots[-1].start, local(11, 23))
        # Low water comes 50 minutes later each day and spoils two hours either side of it.
        # On the 11th that leaves under an hour of light before it, which is no window.
        self.assertEqual(
            self.summaries(data),
            ["Great 10:00–19:00", "Great 11:00–19:00", "Great 12:00–19:32"],
        )
        self.assertEqual(data.outlooks[0].rating, engine.RATING_GREAT)

    def test_low_tide_now(self):
        Clock.set_local(9, 9, 0)
        data = self.refresh(self.make())
        self.assertEqual(data.now.tide, engine.TIDE_LOW)
        self.assertEqual(data.now.rating, engine.RATING_BAD)
        self.assertEqual(data.now.assessment.reason, "Low tide")

    def test_dark_now(self):
        Clock.set_local(9, 3)
        data = self.refresh(self.make())
        self.assertEqual(data.now.rating, engine.RATING_DARK)
        self.assertEqual(data.outlooks[0].rating, engine.RATING_GREAT)
        self.assertLess(abs(data.first_light - local(9, 7, 14)), MINUTE)

    def test_options_override_the_original_settings(self):
        data = self.refresh(self.make(beach_facing=110, gust_max=10))
        self.assertEqual(data.now.assessment.wind_type, engine.WIND_ONSHORE)
        self.assertEqual(data.now.rating, engine.RATING_BAD)
        self.assertEqual(data.now.assessment.reason, "Gusts of 14 km/h")

    def test_the_forecast_is_fetched_once_an_hour(self):
        coordinator = self.make()
        self.refresh(coordinator)
        Clock.advance(minutes=5)
        self.refresh(coordinator)
        self.assertEqual(self.fetches, 1)
        Clock.advance(minutes=55)
        self.refresh(coordinator)
        self.assertEqual(self.fetches, 2)

    def test_the_rating_moves_on_between_fetches(self):
        Clock.set_local(9, 9, 50)
        coordinator = self.make()
        self.assertEqual(self.refresh(coordinator).now.rating, engine.RATING_BAD)
        Clock.advance(minutes=30)  # low tide is over at 10:14
        self.assertEqual(self.refresh(coordinator).now.rating, engine.RATING_GREAT)
        self.assertEqual(self.fetches, 1)

    def test_a_failed_fetch_keeps_the_last_forecast_for_a_while(self):
        coordinator = self.make()
        self.refresh(coordinator)
        self.failure = api.OpenMeteoError("down")
        Clock.advance(hours=2)
        self.assertEqual(self.refresh(coordinator).now.start, local(9, 12))
        self.assertEqual(self.fetches, 2)
        Clock.advance(hours=5)
        with self.assertRaises(module.UpdateFailed):
            self.refresh(coordinator)
        self.failure = None
        self.assertEqual(self.refresh(coordinator).now.start, local(9, 17))

    def test_the_first_fetch_must_succeed(self):
        self.failure = api.OpenMeteoError("down")
        with self.assertRaises(module.UpdateFailed):
            self.refresh(self.make())

    def test_an_unknown_time_zone_falls_back_to_the_default(self):
        self.forecast = forecast(zone="Atlantis/Nowhere")
        self.assertIs(self.refresh(self.make()).zone, UTC)
        self.forecast = forecast(zone=None)
        self.assertIs(self.refresh(self.make()).zone, UTC)

    def test_a_forecast_that_stops_short(self):
        self.forecast = forecast(rows=30)  # ends early on the 9th
        data = self.refresh(self.make())
        self.assertIsNone(data.now)
        self.assertIsNone(data.outlooks[1].rating)
        self.assertIsNone(data.next_high)

    def test_gaps_in_the_forecast(self):
        self.forecast = forecast(wave_height=None, sea_level=None)
        data = self.refresh(self.make())
        self.assertIsNone(data.now.rating)
        self.assertIsNone(data.tide_height)
        self.assertIsNone(data.outlooks[0].rating)


if __name__ == "__main__":
    unittest.main()
