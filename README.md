# Surf Conditions

A Home Assistant custom component that rates the surf at a beach hour by hour, from
a free forecast: great, good, bad or terrible, or flat when there are no waves. It
works out each day's windows, and two blueprints turn them into notifications. No
account or API key is needed.

## What it does

For each spot, every hour is judged on four things. The defaults below are the
ones chosen for Praia do Magoito; every threshold can be changed per spot.

| | Ideal | Good at best | A problem | Terrible |
|---|---|---|---|---|
| Wave height | 0.5 to 2 m | | 2 to 2.5 m | Over 2.5 m |
| Wave period | 8 s or more | 5 to 8 s | Under 5 s | |
| Wind, by its gusts | Offshore under 30 km/h, or calm | Other directions under 30 km/h, offshore up to 45 km/h | Over 30 km/h | 50 km/h or more |
| Tide | Anything else | | Within 2 hours of low water | |

The rating follows from those:

- **Great**: everything is ideal.
- **Good**: no problems, but something is only good at best.
- **Bad**: one problem.
- **Terrible**: two or more problems, or anything in the terrible column.
- **Flat**: waves under 0.5 m, whatever the wind and tide. A day for a paddle board.
- **Dark**: between last light and first light, when nothing is rated.

Values are judged as they are displayed, wave heights and periods to one decimal
and wind to whole km/h, so a gust of 30.2 km/h does not break a limit of 30.

Calm means an average wind under 5 km/h. Offshore wind blows from the land out to
sea, within 45 degrees either side of straight out; the direction the beach faces
is part of the spot's settings.

### Windows

A window is a stretch of consecutive hours of light, at least two hours long. Each
of today, tomorrow and the day after gets an outlook:

- **Great** when it has a window of great hours. The outlook also lists the wider
  stretches that are good or better: `Great 10:00–12:00, surfable 08:00–14:00`.
- **Good** when it has a window of good-or-better hours.
- **Flat** when it has a window of flat hours.
- **Bad** or **terrible** when it has no window.

A day cut in two by low tide lists both windows. Light means first to last light
(civil twilight), and a window is trimmed to it. Today's outlook covers what is
left of the day: a window stays listed until it ends, and after last light the
outlook is dark.

### Where the numbers come from

Everything comes from [Open-Meteo](https://open-meteo.com), fetched once an hour.

- **Wave height** is the total wave height at the nearest sea point of the wave
  model, the same number free forecast sites show. The model's grid is 5 to 9 km,
  so this is the open water just off the beach, not the height of the breaking wave.
- **Wave period** is the peak period of whichever is bigger, the swell or the
  waves raised by the local wind. Short periods mean waves arriving one after
  another with no lulls.
- **Gusts** are the strongest gust during the hour.
- **Tide** comes from Open-Meteo's sea level, relative to mean sea level. Its
  tides run early, so a correction is added. With the default of 27 minutes, a
  week of high and low waters at Magoito came out within 4 minutes of the Cascais
  tide table. To check a spot, compare the Next high tide sensor with a local
  table and adjust the correction in the spot's settings.

## Installation

1. In HACS, add this repository as a custom repository of type Integration.
2. Download Surf Conditions and restart Home Assistant.
3. Add the Surf Conditions integration, once per spot.

### Adding a spot

The first screen asks for a name, the place on the map and the direction the beach
faces: the compass bearing you look along when you stand on the sand facing the
sea. The second screen holds the thresholds, filled with the defaults above.

For Praia do Magoito: latitude 38.8647, longitude -9.4497, facing 290°.

The place, the direction and the thresholds can be changed later with **Configure**
on the integration page. Setting **Low tide lasts** to 0 ignores the tide.

## Entities

Each spot is a device with these sensors:

- Rating, with the reason, a one-line summary of the conditions and the hourly
  forecast as attributes
- Today, Tomorrow, Day after tomorrow: each day's outlook, with the windows, a
  summary line and the conditions during the windows as attributes
- Wave height, Wave period
- Wind gusts, Wind speed, Wind direction, Wind type (offshore, cross-shore, onshore)
- Tide (low, rising, high, falling), Tide height, Next high tide, Next low tide
- Water temperature
- First light, Last light: today's until last light has passed, then tomorrow's

## Notifications

Two blueprints are in `blueprints/automation/surf_conditions`. Import them, then
create an automation from each, picking the spot's sensors and where to send the
message: any notify entity, such as a phone with the Home Assistant app.

- **Morning digest** sends one message at first light with the day's windows,
  when the day is great, good or flat (or whichever ratings you pick):
  `Good 10:00–14:00. Waves 1.7–1.9 m at 9 s, offshore wind gusting to 42 km/h, water 18 °C.`

  [![Import the morning digest](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fnelferr%2Fsurf-conditions-homeassistant-custom-component%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsurf_conditions%2Fmorning_digest.yaml)

- **Live alert** sends a message when the rating improves to great, good or flat
  from something worse, at most once every three hours. Getting light in the
  morning does not count as improving.

  [![Import the live alert](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fnelferr%2Fsurf-conditions-homeassistant-custom-component%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsurf_conditions%2Flive_alert.yaml)

The summary lines are in English with metric units.

## Dashboard

`dashboard.yaml` is a ready-made dashboard for one spot: the rating in colour, the
three outlooks, a coloured square per hour of light, and the conditions as tiles.
It needs [Mushroom](https://github.com/piitaya/lovelace-mushroom). Create a
dashboard, open its raw configuration editor and paste the file in, replacing
`magoito` in the entity ids with your spot's name.

## Development

The rules are in `custom_components/surf_conditions/engine.py`, which has no Home
Assistant imports. The tests run on plain Python 3.12 or later, with nothing to
install:

```bash
python -m unittest discover tests
```

The coordinator and the Open-Meteo client are tested against stand-ins for the Home
Assistant modules they import.

Weather data by [Open-Meteo.com](https://open-meteo.com), licensed under CC BY 4.0
and free for non-commercial use.
