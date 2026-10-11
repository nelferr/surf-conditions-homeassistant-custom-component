"""Sensors: the rating now, each day's outlook, and the conditions behind them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from functools import partial
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import DEGREE, UnitOfLength, UnitOfSpeed, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SpotData, SurfConditionsConfigEntry, SurfConditionsCoordinator
from .engine import (
    RATINGS,
    TIDE_STATES,
    WIND_TYPES,
    Slot,
    TideExtreme,
    Window,
    describe_conditions,
    describe_outlook,
)
from .entity import SurfConditionsEntity


@dataclass(frozen=True, kw_only=True)
class SurfSensorDescription(SensorEntityDescription):
    """A sensor and how to read it from a spot's data."""

    value: Callable[[SpotData], Any]
    attributes: Callable[[SpotData], dict[str, Any]] | None = None


def _now(read: Callable[[Slot], Any]) -> Callable[[SpotData], Any]:
    """Read a value from the current hour, when the forecast covers it."""
    return lambda data: read(data.now) if data.now is not None else None


def _rating_attributes(data: SpotData) -> dict[str, Any]:
    """Explain the rating and carry the hourly forecast for dashboards."""
    now = data.now
    return {
        "reason": now.assessment.reason if now else None,
        "conditions": describe_conditions([now], now.tide) if now else None,
        "forecast": [_forecast_row(slot, data.zone) for slot in data.slots],
    }


def _forecast_row(slot: Slot, zone: tzinfo) -> dict[str, Any]:
    return {
        "time": slot.start.astimezone(zone).isoformat(),
        "rating": slot.rating,
        "reason": slot.assessment.reason,
        "wave_height": slot.hour.wave_height,
        "period": slot.hour.period,
        "wind_gust": slot.hour.wind_gust,
        "wind_type": slot.assessment.wind_type,
        "tide": slot.tide,
    }


def _outlook_attributes(ahead: int, data: SpotData) -> dict[str, Any]:
    """Say when a day's windows are and what they will be like."""
    outlook = data.outlooks[ahead]
    slots = [slot for window in outlook.windows for slot in window.slots]
    return {
        "date": outlook.day.isoformat(),
        "summary": describe_outlook(outlook, data.zone),
        "conditions": describe_conditions(slots) if slots else None,
        "windows": [_times(window, data.zone) for window in outlook.windows],
        "surfable": [_times(window, data.zone) for window in outlook.surfable],
    }


def _times(window: Window, zone: tzinfo) -> dict[str, str]:
    return {
        "start": window.start.astimezone(zone).isoformat(),
        "end": window.end.astimezone(zone).isoformat(),
    }


def _tide_attributes(
    read: Callable[[SpotData], TideExtreme | None], data: SpotData
) -> dict[str, Any]:
    extreme = read(data)
    return {"height": round(extreme.height, 2) if extreme else None}


def _outlook(key: str, ahead: int, icon: str) -> SurfSensorDescription:
    return SurfSensorDescription(
        key=key,
        device_class=SensorDeviceClass.ENUM,
        options=RATINGS,
        icon=icon,
        value=lambda data: data.outlooks[ahead].rating,
        attributes=partial(_outlook_attributes, ahead),
    )


SENSORS: tuple[SurfSensorDescription, ...] = (
    SurfSensorDescription(
        key="rating",
        device_class=SensorDeviceClass.ENUM,
        options=RATINGS,
        icon="mdi:surfing",
        value=_now(lambda slot: slot.rating),
        attributes=_rating_attributes,
    ),
    _outlook("today", 0, "mdi:calendar-today"),
    _outlook("tomorrow", 1, "mdi:calendar-arrow-right"),
    _outlook("day_after_tomorrow", 2, "mdi:calendar-end"),
    SurfSensorDescription(
        key="wave_height",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:waves",
        value=_now(lambda slot: slot.hour.wave_height),
    ),
    SurfSensorDescription(
        key="wave_period",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:sine-wave",
        value=_now(lambda slot: slot.hour.period),
    ),
    SurfSensorDescription(
        key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:weather-windy",
        value=_now(lambda slot: slot.hour.wind_gust),
    ),
    SurfSensorDescription(
        key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:weather-windy-variant",
        value=_now(lambda slot: slot.hour.wind_speed),
    ),
    SurfSensorDescription(
        key="wind_direction",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        icon="mdi:compass-outline",
        value=_now(lambda slot: slot.hour.wind_direction),
    ),
    SurfSensorDescription(
        key="wind_type",
        device_class=SensorDeviceClass.ENUM,
        options=WIND_TYPES,
        icon="mdi:windsock",
        value=_now(lambda slot: slot.assessment.wind_type),
    ),
    SurfSensorDescription(
        key="tide_height",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:wave",
        value=lambda data: data.tide_height,
    ),
    SurfSensorDescription(
        key="tide",
        device_class=SensorDeviceClass.ENUM,
        options=TIDE_STATES,
        icon="mdi:swap-vertical",
        value=_now(lambda slot: slot.tide),
    ),
    SurfSensorDescription(
        key="next_high_tide",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:arrow-up-bold",
        value=lambda data: data.next_high.time if data.next_high else None,
        attributes=partial(_tide_attributes, lambda data: data.next_high),
    ),
    SurfSensorDescription(
        key="next_low_tide",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:arrow-down-bold",
        value=lambda data: data.next_low.time if data.next_low else None,
        attributes=partial(_tide_attributes, lambda data: data.next_low),
    ),
    SurfSensorDescription(
        key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:thermometer-water",
        value=_now(lambda slot: slot.hour.water_temperature),
    ),
    SurfSensorDescription(
        key="first_light",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-up",
        value=lambda data: data.first_light,
    ),
    SurfSensorDescription(
        key="last_light",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-down",
        value=lambda data: data.last_light,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SurfConditionsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a spot's sensors."""
    coordinator = entry.runtime_data
    async_add_entities(SurfSensor(coordinator, description) for description in SENSORS)


class SurfSensor(SurfConditionsEntity, SensorEntity):
    """One value of a spot."""

    entity_description: SurfSensorDescription
    # The hourly forecast is for dashboards; storing every version would only bloat the database.
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(
        self, coordinator: SurfConditionsCoordinator, description: SurfSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return what explains the value, for the sensors that have something to add."""
        read = self.entity_description.attributes
        return read(self.coordinator.data) if read else None
