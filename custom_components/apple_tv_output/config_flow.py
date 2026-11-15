"""Config flow for Apple TV Audio Output: one entry, and options for the default speakers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .apple_tv import apple_tv_players
from .const import CONF_DEFAULT_SPEAKERS, DOMAIN
from .speakers import async_scan, get_cache

try:
    import probatio as vol  # Home Assistant 2026.10 and newer
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)

CONF_APPLE_TV = "apple_tv"
CONF_SPEAKERS = "speakers"


class AppleTVOutputConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the actions; the Apple TVs themselves come from the Apple TV integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the single entry."""
        if user_input is not None:
            return self.async_create_entry(title="Apple TV Audio Output", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AppleTVOutputOptionsFlow()


class AppleTVOutputOptionsFlow(OptionsFlow):
    """Choose an Apple TV, then the speakers it should always play to."""

    def __init__(self) -> None:
        self._registry_id: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        players = apple_tv_players(self.hass)
        if not players:
            return self.async_abort(reason="no_apple_tvs")
        if user_input is not None:
            self._registry_id = user_input[CONF_APPLE_TV]
            return await self.async_step_speakers()

        def label(entity_id: str) -> str:
            state = self.hass.states.get(entity_id)
            return state.name if state else entity_id

        options = [SelectOptionDict(value=p.id, label=label(p.entity_id)) for p in players]
        schema = vol.Schema(
            {vol.Required(CONF_APPLE_TV, default=players[0].id): SelectSelector(SelectSelectorConfig(options=options))}
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_speakers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._registry_id is not None
        defaults: dict[str, list[str]] = dict(self.config_entry.options.get(CONF_DEFAULT_SPEAKERS, {}))
        if user_input is not None:
            if speakers := [s for s in user_input.get(CONF_SPEAKERS, []) if s.strip()]:
                defaults[self._registry_id] = speakers
            else:
                defaults.pop(self._registry_id, None)
            return self.async_create_entry(data={**self.config_entry.options, CONF_DEFAULT_SPEAKERS: defaults})

        cache = get_cache(self.hass)
        if cache.scanned_at is None:
            try:
                cache = await async_scan(self.hass)
            except Exception as err:
                # Speakers can still be typed in.
                _LOGGER.debug("Scan for AirPlay speakers failed: %s", err)
        current = defaults.get(self._registry_id, [])
        names = sorted({d.name for d in cache.all()} | set(current), key=str.casefold)
        schema = vol.Schema(
            {
                vol.Optional(CONF_SPEAKERS, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=names, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="speakers", data_schema=schema)
