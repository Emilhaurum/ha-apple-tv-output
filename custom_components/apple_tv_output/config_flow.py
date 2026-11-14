"""Config flow for Apple TV Audio Output: one entry, nothing to configure."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class AppleTVOutputConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the actions; the Apple TVs themselves come from the Apple TV integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the single entry."""
        if user_input is not None:
            return self.async_create_entry(title="Apple TV Audio Output", data={})
        return self.async_show_form(step_id="user")
