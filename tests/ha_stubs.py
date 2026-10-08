"""Minimal stand-ins for the Home Assistant modules the coordinator imports.

They let the coordinator's update loop run under plain unittest. They are not a
substitute for testing inside Home Assistant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import enum
import sys
import types

LOCAL = timezone(timedelta(hours=1))  # Lisbon summer time


class Clock:
    """The time the stubbed dt_util reports."""

    now = datetime(2026, 10, 9, 9, 30, tzinfo=timezone.utc)

    @classmethod
    def set_local(cls, day: int, hour: int, minute: int = 0) -> None:
        cls.now = datetime(2026, 10, day, hour, minute, tzinfo=LOCAL).astimezone(timezone.utc)

    @classmethod
    def advance(cls, **kwargs) -> None:
        cls.now += timedelta(**kwargs)


class FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _Generic:
    def __class_getitem__(cls, item):
        return cls


class _DataUpdateCoordinator(_Generic):
    def __init__(self, hass, logger, *, config_entry=None, name=None, update_interval=None):
        self.hass = hass
        self.config_entry = config_entry
        self.update_interval = update_interval
        self.data = None

    async def async_refresh(self):
        self.data = await self._async_update_data()

    async_config_entry_first_refresh = async_refresh


def install() -> None:
    """Register the stub modules. Safe to call more than once."""
    if "homeassistant" in sys.modules:
        return

    def module(name, **members):
        mod = types.ModuleType(name)
        mod.__dict__.update(members)
        sys.modules[name] = mod
        return mod

    module("homeassistant")
    module("homeassistant.helpers")
    module("homeassistant.util")
    module("homeassistant.config_entries", ConfigEntry=_Generic)
    module(
        "homeassistant.const",
        CONF_LATITUDE="latitude",
        CONF_LONGITUDE="longitude",
        Platform=enum.Enum("Platform", "SENSOR"),
    )
    module("homeassistant.core", HomeAssistant=FakeHass)
    module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
    module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DataUpdateCoordinator,
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
    )
    module(
        "homeassistant.util.dt",
        utcnow=lambda: Clock.now,
        DEFAULT_TIME_ZONE=timezone.utc,
        get_time_zone=lambda name: LOCAL if name == "Europe/Lisbon" else None,
    )
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        # Only the names the Open-Meteo client mentions; no request is ever made in the tests.
        module(
            "aiohttp",
            ClientSession=object,
            ClientTimeout=lambda **kwargs: None,
            ClientError=type("ClientError", (Exception,), {}),
        )
