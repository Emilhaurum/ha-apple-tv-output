"""Config flow for Apple TV Audio Output: find an Apple TV, pair it, and choose its default speakers."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components import zeroconf
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import pyatv
from pyatv.const import DeviceModel, OperatingSystem, PairingRequirement, Protocol

from .apple_tv import is_device_entry
from .common import key
from .const import (
    APPLE_TV_DOMAIN,
    CONF_ADDRESS,
    CONF_CREDENTIALS,
    CONF_DEFAULT_SPEAKERS,
    CONF_IDENTIFIERS,
    DOMAIN,
    SCAN_TIMEOUT,
)
from .speakers import async_scan, get_cache

try:
    import probatio as vol  # Home Assistant 2026.10 and newer
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE = "device"
CONF_PIN = "pin"
CONF_SPEAKERS = "speakers"
# Shown on the Apple TV while pairing.
PAIRING_NAME = "Home Assistant (Apple TV Audio Output)"
# Pairing these gives the control channel that changes the outputs: AirPlay (which carries it on
# tvOS 15 and newer) and, on older tvOS, the separate remote control (MRP) service.
PAIR_PROTOCOLS = (Protocol.AirPlay, Protocol.MRP)
NOT_APPLE_TVS = {
    DeviceModel.HomePod,
    DeviceModel.HomePodMini,
    DeviceModel.AirPortExpress,
    DeviceModel.AirPortExpressGen2,
}
# Protocols whose pairing can be done; NotNeeded, Disabled and Unsupported are skipped.
PAIRABLE = {PairingRequirement.Mandatory, PairingRequirement.Optional}


def _is_apple_tv(conf: Any) -> bool:
    """Return whether a device found by the scan is an Apple TV (not a HomePod or another speaker)."""
    info = conf.device_info
    if info.model in NOT_APPLE_TVS or not any(conf.get_service(p) is not None for p in PAIR_PROTOCOLS):
        return False
    # The operating system comes from what the device announces and can be unknown; a remote control
    # (MRP) service also marks an Apple TV.
    return info.operating_system is OperatingSystem.TvOS or conf.get_service(Protocol.MRP) is not None


def _needs_pairing(conf: Any) -> list[Protocol]:
    """Return the protocols to pair, in order.

    Optional pairing is done too: the control channel over AirPlay needs AirPlay credentials.
    """
    return [
        protocol
        for protocol in PAIR_PROTOCOLS
        if (service := conf.get_service(protocol)) is not None and service.pairing in PAIRABLE
    ]


class AppleTVOutputConfigFlow(ConfigFlow, domain=DOMAIN):
    """Find an Apple TV on the network and pair it."""

    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, Any] = {}
        self._conf: Any = None
        self._to_pair: list[Protocol] = []
        self._credentials: dict[str, str] = {}
        self._handler: Any = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AppleTVOutputOptionsFlow()

    async def _scan(self, identifiers: set[str] | None = None) -> list[Any]:
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        confs = await pyatv.scan(self.hass.loop, timeout=SCAN_TIMEOUT, identifier=identifiers, aiozc=aiozc)
        return [conf for conf in confs if _is_apple_tv(conf)]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose one of the Apple TVs found on the network."""
        if user_input is not None:
            conf = self._found[user_input[CONF_DEVICE]]
            await self.async_set_unique_id(conf.identifier)
            self._abort_if_unique_id_configured()
            return await self._async_start_pairing(conf)

        configured = {e.unique_id for e in self._async_current_entries(include_ignore=False)}
        self._found = {c.identifier: c for c in await self._scan() if c.identifier not in configured}
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        options = [SelectOptionDict(value=i, label=f"{c.name} ({c.address})") for i, c in self._found.items()]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): SelectSelector(SelectSelectorConfig(options=options))}),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The Apple TV no longer accepts the pairing: pair it again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", description_placeholders={"name": entry.title})
        confs = await self._scan(set(entry.data.get(CONF_IDENTIFIERS, [])))
        if not confs:
            return self.async_abort(reason="device_not_found")
        return await self._async_start_pairing(confs[0])

    async def _async_start_pairing(self, conf: Any) -> ConfigFlowResult:
        self._conf = conf
        self._to_pair = _needs_pairing(conf)
        self._credentials = {}
        return await self._async_pair_next()

    async def _async_begin(self) -> None:
        protocol = self._to_pair[0]
        self._handler = await pyatv.pair(
            self._conf, protocol, self.hass.loop, session=async_get_clientsession(self.hass), name=PAIRING_NAME
        )
        await self._handler.begin()

    async def _async_close_handler(self) -> None:
        if self._handler is not None:
            handler, self._handler = self._handler, None
            await handler.close()

    async def _async_pair_next(self) -> ConfigFlowResult:
        if not self._to_pair:
            return await self._async_finish()
        try:
            await self._async_begin()
        except Exception as err:
            _LOGGER.debug("Could not start pairing %s: %s", self._conf.name, err)
            await self._async_close_handler()
            return self.async_abort(reason="cannot_connect")
        if not self._handler.device_provides_pin:
            # Only very old Apple TVs ask for a PIN to be typed on them; they are not supported.
            await self._async_close_handler()
            return self.async_abort(reason="pairing_not_supported")
        return await self.async_step_pin()

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Type the PIN the Apple TV shows."""
        errors: dict[str, str] = {}
        protocol = self._to_pair[0]
        if user_input is not None:
            try:
                self._handler.pin(int(str(user_input[CONF_PIN]).strip()))
                await self._handler.finish()
                paired = self._handler.has_paired
            except Exception as err:
                _LOGGER.debug("Pairing %s with %s failed: %s", protocol.name, self._conf.name, err)
                paired = False
            if paired:
                self._credentials[str(protocol.value)] = self._handler.service.credentials
                await self._async_close_handler()
                self._to_pair.pop(0)
                return await self._async_pair_next()
            # A failed attempt ends the pairing on the Apple TV; start again for a new PIN.
            errors["base"] = "invalid_pin"
            await self._async_close_handler()
            try:
                await self._async_begin()
            except Exception:
                await self._async_close_handler()
                return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema({vol.Required(CONF_PIN): TextSelector()}),
            description_placeholders={"name": self._conf.name, "protocol": protocol.name},
            errors=errors,
        )

    async def _async_finish(self) -> ConfigFlowResult:
        conf = self._conf
        data = {
            CONF_ADDRESS: str(conf.address),
            CONF_IDENTIFIERS: list(conf.all_identifiers),
            CONF_CREDENTIALS: self._credentials,
        }
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_create_entry(title=conf.name, data=data, options=self._legacy_options(conf))

    def _legacy_options(self, conf: Any) -> dict[str, Any]:
        """Take over the default speakers a version 1 entry had for this Apple TV."""
        keys = {key(i) for i in conf.all_identifiers}
        registry = er.async_get(self.hass)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if is_device_entry(entry):
                continue
            for registry_id, speakers in entry.options.get(CONF_DEFAULT_SPEAKERS, {}).items():
                player = registry.async_get(registry_id)
                if speakers and player and player.platform == APPLE_TV_DOMAIN and key(player.unique_id) in keys:
                    return {CONF_DEFAULT_SPEAKERS: list(speakers)}
        return {}

    @callback
    def async_remove(self) -> None:
        """Close a pairing that was left unfinished when the flow is removed."""
        if self._handler is not None:
            handler, self._handler = self._handler, None
            self.hass.async_create_task(handler.close(), eager_start=True)


class AppleTVOutputOptionsFlow(OptionsFlow):
    """Choose the speakers the Apple TV always plays to when it wakes up."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not is_device_entry(self.config_entry):
            return self.async_abort(reason="legacy_entry")
        if user_input is not None:
            speakers = [s for s in user_input.get(CONF_SPEAKERS, []) if s.strip()]
            return self.async_create_entry(data={**self.config_entry.options, CONF_DEFAULT_SPEAKERS: speakers})

        cache = get_cache(self.hass)
        if cache.scanned_at is None:
            try:
                cache = await async_scan(self.hass)
            except Exception as err:
                # Speakers can still be typed in.
                _LOGGER.debug("Scan for AirPlay speakers failed: %s", err)
        current = list(self.config_entry.options.get(CONF_DEFAULT_SPEAKERS, []))
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
        return self.async_show_form(
            step_id="init", data_schema=schema, description_placeholders={"name": self.config_entry.title}
        )
