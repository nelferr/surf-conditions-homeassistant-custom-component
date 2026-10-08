"""Setup screens for Surf Conditions: one entry per spot."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OpenMeteoError, OpenMeteoRefused, async_fetch
from .const import CONF_LOCATION, CONF_NAME, CONF_TIDE_OFFSET, DEFAULT_TIDE_OFFSET, DOMAIN
from .engine import Rules

_DEFAULTS = Rules()


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _rule(name: str) -> vol.Required:
    return vol.Required(name, default=getattr(_DEFAULTS, name))


_PLACE = {
    vol.Required(CONF_LOCATION): selector.LocationSelector(
        selector.LocationSelectorConfig(radius=False, icon="mdi:surfing")
    ),
    _rule("beach_facing"): _number(0, 359, 1, "°"),
}
_RULES = {
    _rule("wave_min"): _number(0, 5, 0.1, "m"),
    _rule("wave_max"): _number(0.1, 10, 0.1, "m"),
    _rule("wave_terrible"): _number(0.1, 15, 0.1, "m"),
    _rule("period_ideal"): _number(1, 25, 0.5, "s"),
    _rule("period_min"): _number(0, 25, 0.5, "s"),
    _rule("gust_max"): _number(1, 150, 1, "km/h"),
    _rule("offshore_gust_max"): _number(1, 150, 1, "km/h"),
    _rule("gust_terrible"): _number(1, 200, 1, "km/h"),
    _rule("calm_wind"): _number(0, 30, 1, "km/h"),
    _rule("low_tide_hours"): _number(0, 6, 0.25, "h"),
    _rule("min_window_hours"): _number(1, 12, 1, "h"),
    vol.Required(CONF_TIDE_OFFSET, default=DEFAULT_TIDE_OFFSET): _number(-180, 180, 1, "min"),
}

SPOT_SCHEMA = vol.Schema({vol.Required(CONF_NAME): selector.TextSelector(), **_PLACE})
RULES_SCHEMA = vol.Schema(_RULES)
OPTIONS_SCHEMA = vol.Schema({**_PLACE, **_RULES})


class SurfConditionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a spot: where it is first, then what makes it good."""

    VERSION = 1

    def __init__(self) -> None:
        self._spot: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the name, the place and the way the beach faces."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_NAME: user_input[CONF_NAME]})
            location = user_input[CONF_LOCATION]
            try:
                forecast = await async_fetch(
                    async_get_clientsession(self.hass),
                    location[CONF_LATITUDE],
                    location[CONF_LONGITUDE],
                )
            except OpenMeteoRefused:
                errors["base"] = "no_waves"
            except OpenMeteoError:
                errors["base"] = "cannot_connect"
            else:
                if any(hour.wave_height is not None for hour in forecast.hours):
                    self._spot = user_input
                    return await self.async_step_rules()
                errors["base"] = "no_waves"
        config = self.hass.config
        home = {CONF_LATITUDE: config.latitude, CONF_LONGITUDE: config.longitude}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                SPOT_SCHEMA, user_input or {CONF_LOCATION: home}
            ),
            errors=errors,
        )

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the thresholds, starting from the defaults."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._spot[CONF_NAME], data={**self._spot, **user_input}
            )
        return self.async_show_form(step_id="rules", data_schema=RULES_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SurfConditionsOptionsFlow:
        """Return the options flow."""
        return SurfConditionsOptionsFlow()


class SurfConditionsOptionsFlow(OptionsFlow):
    """Move the spot or change its thresholds."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show everything but the name, filled with the current values."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, current),
        )
