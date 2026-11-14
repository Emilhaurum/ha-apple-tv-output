"""Helpers shared by the modules of Apple TV Audio Output."""

from __future__ import annotations

import re

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

ISSUE_URL = "https://github.com/Emilhaurum/ha-apple-tv-output/issues"

# AirPlay ids: a MAC address (with colons, dashes or nothing between the bytes) or a UUID.
_MAC = re.compile(r"^[0-9A-F]{2}(?:([:-]?)[0-9A-F]{2})(?:\1[0-9A-F]{2}){4}$", re.I)
_UUID = re.compile(r"^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$", re.I)


def key(identifier: str) -> str:
    """Return a form of an id that compares equal however it is written."""
    return re.sub(r"[^0-9a-z]", "", identifier.casefold())


def is_id(text: str) -> bool:
    """Return whether the text is an AirPlay id rather than a name."""
    return bool(_MAC.match(text) or _UUID.match(text))


def canonical(identifier: str) -> str:
    """Write a MAC address the way the Apple TV reports it: upper case with colons."""
    if _MAC.match(identifier):
        digits = key(identifier).upper()
        return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
    return identifier


def error(cls: type[HomeAssistantError], translation_key: str, **placeholders: str) -> HomeAssistantError:
    """Return a translated error."""
    return cls(translation_domain=DOMAIN, translation_key=translation_key, translation_placeholders=placeholders)
