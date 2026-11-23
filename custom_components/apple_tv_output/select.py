"""Dropdown to choose the speaker an Apple TV plays to."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .apple_tv import connected
from .entity import AppleTVOutputEntity
from .outputs import Mode, async_change
from .speakers import async_add_listener, async_resolve, get_cache

if TYPE_CHECKING:
    from . import AppleTVOutputConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: AppleTVOutputConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([OutputSelect(entry.runtime_data, "output")])


class OutputSelect(AppleTVOutputEntity, SelectEntity):
    """Choosing a speaker sends the sound there only, like set_output.

    When the Apple TV plays to several speakers, or to none, no option is selected.
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The options are the speakers found on the network; update them after every scan.
        self.async_on_remove(async_add_listener(self.hass, self._handle_update))

    @callback
    def _update_from_connection(self) -> None:
        current = self.speaker_names
        names = {d.name for d in get_cache(self.connection.hass).all()} | set(current)
        if not current and self.outputs:
            # Playing only through the Apple TV itself, which can be chosen too.
            current = [self.connection.name]
            names.add(self.connection.name)
        self._attr_options = sorted(names, key=str.casefold)
        self._attr_current_option = current[0] if len(current) == 1 else None

    async def async_select_option(self, option: str) -> None:
        tv = connected(self.connection)
        speakers = await async_resolve(self.hass, [option])
        await async_change(self.hass, tv, speakers, Mode.SET)
