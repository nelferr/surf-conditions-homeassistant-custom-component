"""Tests for the Open-Meteo client, run against stubbed Home Assistant modules."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

import ha_stubs  # noqa: E402

ha_stubs.install()

from custom_components.surf_conditions import api  # noqa: E402

MARINE = {
    "timezone": "Europe/Lisbon",
    "hourly": {
        "time": [0, 3600, 7200],
        "wave_height": [1.0, 1.1, None],
        "wave_period": [7.0, 7.1, 7.2],
        "swell_wave_height": [0.9, 0.3, 0.9],
        "swell_wave_period": [8.0, 8.1, 8.2],
        "swell_wave_peak_period": [10.0, 10.1, None],
        "wind_wave_height": [0.4, 0.8, 0.2],
        "wind_wave_period": [3.0, 3.5, 3.1],
        "wind_wave_peak_period": [4.0, 4.5, 4.1],
        "sea_surface_temperature": [18.0, 18.1, 18.2],
        "sea_level_height_msl": [0.1, 0.2, 0.3],
    },
}
WIND = {
    "hourly": {
        "time": [0, 3600, 7200],
        "wind_speed_10m": [10.0, 12.0, 14.0],
        "wind_gusts_10m": [20.0, 25.0, 30.0],
        "wind_direction_10m": [90, 100, 110],
    },
}


class FakeResponse:
    def __init__(self, answer):
        self.answer = answer

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, content_type=None):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class FakeSession:
    def __init__(self, marine=MARINE, wind=WIND):
        self.answers = {api.MARINE_URL: marine, api.FORECAST_URL: wind}
        self.asked = {}

    def get(self, url, params=None, timeout=None):
        self.asked[url] = params
        return FakeResponse(self.answers[url])


def fetch(session):
    return asyncio.run(api.async_fetch(session, 38.8647, -9.4497))


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.forecast = api.parse(MARINE, WIND)
        self.first, self.second, self.third = self.forecast.hours

    def test_one_row_per_hour_in_utc(self):
        self.assertEqual(self.first.time, datetime(1970, 1, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(self.third.time, datetime(1970, 1, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(self.forecast.time_zone, "Europe/Lisbon")

    def test_values_are_joined_by_time(self):
        self.assertEqual(self.first.wave_height, 1.0)
        self.assertEqual(self.first.wind_speed, 10.0)
        self.assertEqual(self.first.wind_direction, 90)
        self.assertEqual(self.first.water_temperature, 18.0)
        self.assertEqual(self.first.sea_level, 0.1)
        self.assertIsNone(self.third.wave_height)

    def test_a_gust_belongs_to_the_hour_before_its_stamp(self):
        self.assertEqual(self.first.wind_gust, 25.0)
        self.assertEqual(self.second.wind_gust, 30.0)
        self.assertEqual(self.third.wind_gust, 30.0)  # nothing later to take it from

    def test_the_period_is_that_of_the_bigger_waves(self):
        self.assertEqual(self.first.period, 10.0)  # swell 0.9 m against 0.4 m of wind waves
        self.assertEqual(self.second.period, 4.5)  # wind waves 0.8 m against 0.3 m of swell

    def test_mean_periods_stand_in_for_missing_peak_periods(self):
        self.assertEqual(self.third.period, 8.2)
        bare = {"hourly": {"time": [0], "wave_height": [1.0], "wave_period": [7.0]}}
        self.assertEqual(api.parse(bare, WIND).hours[0].period, 7.0)

    def test_hours_without_wind_keep_their_waves(self):
        hour = api.parse(MARINE, {"hourly": {"time": []}}).hours[0]
        self.assertEqual(hour.wave_height, 1.0)
        self.assertIsNone(hour.wind_speed)
        self.assertIsNone(hour.wind_gust)


class FetchTest(unittest.TestCase):
    def test_both_services_are_asked_for_the_same_hours(self):
        session = FakeSession()
        forecast = fetch(session)
        self.assertEqual(len(forecast.hours), 3)
        marine, wind = session.asked[api.MARINE_URL], session.asked[api.FORECAST_URL]
        for params in (marine, wind):
            self.assertEqual((params["latitude"], params["longitude"]), (38.8647, -9.4497))
            self.assertEqual((params["past_days"], params["forecast_days"]), (1, 4))
            self.assertEqual((params["timeformat"], params["timezone"]), ("unixtime", "auto"))
        self.assertEqual(marine["cell_selection"], "sea")
        self.assertIn("sea_level_height_msl", marine["hourly"].split(","))
        self.assertEqual(wind["wind_speed_unit"], "kmh")
        self.assertEqual(wind["hourly"], "wind_speed_10m,wind_gusts_10m,wind_direction_10m")

    def test_a_refusal_says_why(self):
        session = FakeSession(marine={"error": True, "reason": "No data for this location"})
        with self.assertRaises(api.OpenMeteoRefused) as caught:
            fetch(session)
        self.assertEqual(str(caught.exception), "No data for this location")

    def test_unusable_answers_and_failed_requests(self):
        for answer in (["not", "a", "dict"], {"no": "hourly"}, TimeoutError(), ValueError("not JSON")):
            with self.assertRaises(api.OpenMeteoError) as caught:
                fetch(FakeSession(wind=answer))
            self.assertNotIsInstance(caught.exception, api.OpenMeteoRefused)


if __name__ == "__main__":
    unittest.main()
