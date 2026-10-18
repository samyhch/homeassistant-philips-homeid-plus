"""Pet Series camera options, with all login flows excluded."""
from __future__ import annotations
from typing import Any, Dict, Optional
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from .bridge import (
    CAMERA_MODE_ON_DEMAND, CAMERA_MODES, IDLE_TIMEOUT,
    IDLE_TIMEOUT_MAX_MINUTES, IDLE_TIMEOUT_MIN_MINUTES,
)
from .const import CONF_CAMERA_MODE, CONF_IDLE_TIMEOUT

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Adjust behaviour that does not require re-authentication."""

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}.get(
            CONF_CAMERA_MODE, CAMERA_MODE_ON_DEMAND
        )
        if current not in CAMERA_MODES:
            current = CAMERA_MODE_ON_DEMAND
        merged = {**self.config_entry.data, **self.config_entry.options}
        idle_default = merged.get(
            CONF_IDLE_TIMEOUT, int(IDLE_TIMEOUT.total_seconds() // 60)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CAMERA_MODE, default=current
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(CAMERA_MODES),
                        translation_key="camera_mode",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_IDLE_TIMEOUT, default=idle_default
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=IDLE_TIMEOUT_MIN_MINUTES,
                        max=IDLE_TIMEOUT_MAX_MINUTES,
                        step=1,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
