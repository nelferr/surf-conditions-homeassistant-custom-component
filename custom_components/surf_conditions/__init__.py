"""Surf Conditions: a surf rating, tides and the best windows for a beach."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SurfConditionsConfigEntry, SurfConditionsCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SurfConditionsConfigEntry) -> bool:
    """Set up one spot from its config entry."""
    coordinator = SurfConditionsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The place and the thresholds are options, so changing them must rebuild the spot.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SurfConditionsConfigEntry) -> bool:
    """Unload a spot."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: SurfConditionsConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
