"""This integration's own connection to one paired Apple TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pyatv
from pyatv.const import PowerState, Protocol
from pyatv.exceptions import AuthenticationError, InvalidCredentialsError, NoCredentialsError
from pyatv.interface import AudioListener, DeviceListener, PowerListener

from . import const
from .common import key

_LOGGER = logging.getLogger(__name__)

# Errors that only pairing again can fix.
AUTH_ERRORS = (AuthenticationError, InvalidCredentialsError, NoCredentialsError)


class AppleTVConnection(DeviceListener, PowerListener, AudioListener):
    """Connects to one Apple TV with its own credentials, reconnects, and reports what changes.

    Listeners are told about every change (connected, disconnected, outputs, volume, power); wake
    listeners only when the Apple TV wakes up.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.atv: Any = None
        # True when on, False when off, None when not known (not connected, or not reported).
        self.power_on: bool | None = None
        self._listeners: list[Callable[[], None]] = []
        self._wake_listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._attempts = 0
        # When and in which power state the connection was last lost, to tell a sleep from a glitch.
        self._lost_at: float | None = None
        self._power_before_loss: bool | None = None

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def identifiers(self) -> frozenset[str]:
        """Return the Apple TV's ids, as key() forms."""
        return frozenset(key(i) for i in self.entry.data.get(const.CONF_IDENTIFIERS, []))

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_add_wake_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._wake_listeners.append(listener)
        return lambda: self._wake_listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _woke(self) -> None:
        _LOGGER.debug("%s woke up", self.name)
        for listener in list(self._wake_listeners):
            listener()

    @callback
    def async_start(self) -> None:
        """Connect in the background, retrying until connected."""
        self._stopped = False
        self._start_connecting()

    async def async_stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self.atv is not None:
            atv, self.atv = self.atv, None
            atv.close()

    @callback
    def _start_connecting(self) -> None:
        if self._stopped or (self._task is not None and not self._task.done()):
            return
        self._task = self.entry.async_create_background_task(
            self.hass, self._connect_loop(), f"{const.DOMAIN} connect {self.name}"
        )

    async def _connect_loop(self) -> None:
        while not self._stopped and self.atv is None:
            try:
                await self._connect_once()
            except AUTH_ERRORS as err:
                _LOGGER.warning("%s no longer accepts the pairing (%s); pair it again", self.name, err)
                self.entry.async_start_reauth(self.hass)
                return
            except Exception as err:
                _LOGGER.debug("Could not connect to %s: %s", self.name, err)
            if self.atv is not None:
                return
            self._attempts += 1
            delay = min(const.RECONNECT_MAX, const.RECONNECT_MIN * 2 ** (self._attempts - 1))
            _LOGGER.debug("Connecting to %s again in %s seconds", self.name, delay)
            await asyncio.sleep(delay)

    async def _find(self) -> Any:
        """Find the Apple TV on the network: at its last address first, then anywhere."""
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        identifiers = set(self.entry.data.get(const.CONF_IDENTIFIERS, []))
        address = self.entry.data.get(const.CONF_ADDRESS)
        confs = []
        if address:
            confs = await pyatv.scan(
                self.hass.loop, timeout=const.SCAN_TIMEOUT, identifier=identifiers, hosts=[address], aiozc=aiozc
            )
        if not confs:
            confs = await pyatv.scan(self.hass.loop, timeout=const.SCAN_TIMEOUT, identifier=identifiers, aiozc=aiozc)
        return confs[0] if confs else None

    async def _connect_once(self) -> None:
        conf = await self._find()
        if conf is None:
            _LOGGER.debug("%s was not found on the network", self.name)
            return
        for protocol, credentials in self.entry.data.get(const.CONF_CREDENTIALS, {}).items():
            if conf.get_service(Protocol(int(protocol))) is not None:
                conf.set_credentials(Protocol(int(protocol)), credentials)
        atv = await pyatv.connect(conf, self.hass.loop, session=async_get_clientsession(self.hass))
        if self._stopped:
            atv.close()
            return
        atv.listener = self
        atv.power.listener = self
        atv.audio.listener = self
        self.atv = atv
        self._attempts = 0
        if (address := str(conf.address)) != self.entry.data.get(const.CONF_ADDRESS):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, const.CONF_ADDRESS: address}
            )
        self.power_on = self._read_power()
        _LOGGER.debug("Connected to %s (power %s)", self.name, self.power_on)

        # The Apple TV may drop the connection while it sleeps: reconnecting to it switched on counts as
        # a wake-up if it was off before, or if the connection was gone long enough for a sleep.
        lost_at, self._lost_at = self._lost_at, None
        if lost_at is not None and self.power_on:
            outage = time.monotonic() - lost_at
            if self._power_before_loss is False or outage >= const.WAKE_AFTER_OUTAGE:
                self._woke()
        self._notify()

    def _read_power(self) -> bool | None:
        try:
            state = self.atv.power.power_state
        except Exception:
            return None
        return {PowerState.On: True, PowerState.Off: False}.get(state)

    @callback
    def _disconnected(self) -> None:
        if self.atv is None:
            return
        self._power_before_loss = self.power_on
        self._lost_at = time.monotonic()
        self.atv = None
        self.power_on = None
        self._notify()
        self._start_connecting()

    # pyatv listener callbacks. They run in the event loop.

    def connection_lost(self, exception: Exception) -> None:
        _LOGGER.debug("Lost the connection to %s: %s", self.name, exception)
        self._disconnected()

    def connection_closed(self) -> None:
        _LOGGER.debug("The connection to %s was closed", self.name)
        self._disconnected()

    def powerstate_update(self, old_state: PowerState, new_state: PowerState) -> None:
        was = self.power_on
        self.power_on = {PowerState.On: True, PowerState.Off: False}.get(new_state)
        self._notify()
        if was is False and self.power_on:
            self._woke()

    def outputdevices_update(self, old_devices: Any, new_devices: Any) -> None:
        self._notify()

    def volume_update(self, old_level: float, new_level: float) -> None:
        self._notify()

    def volume_device_update(self, output_device: Any, old_level: float, new_level: float) -> None:
        self._notify()
