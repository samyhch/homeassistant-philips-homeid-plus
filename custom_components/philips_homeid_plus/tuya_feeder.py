"""HomeID-authenticated Tuya controls for Philips Pet Series feeders."""

from __future__ import annotations

import json

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .cloud_api import PhilipsCloudAPI
from .const import CONF_CLOUD_REFRESH_TOKEN, CONF_TUYA_DEVICE_ID, CONF_TUYA_DP, DOMAIN, OAUTH_CLIENT_HOMEID


class PhilipsTuyaFeederButton(ButtonEntity):
    """Dispense one portion using the existing HomeID OAuth session."""

    _attr_has_entity_name = True
    _attr_name = "Dispense one portion"
    _attr_icon = "mdi:food-drumstick"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.device_id = entry.data[CONF_TUYA_DEVICE_ID]
        self.dp = entry.data[CONF_TUYA_DP]
        self._attr_unique_id = f"{self.device_id}_dispense_one_portion"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)}, name=entry.title,
            manufacturer="Philips", model=entry.data.get("model", "Pet Series feeder"),
        )

    async def async_press(self) -> None:
        """Refresh the existing HomeID session and publish one feed DP."""
        try:
            from .homeid_tuya import session_for
            await session_for(self.hass, self.entry).publish(self.device_id, {self.dp: 1.0})
        except Exception as err:
            raise HomeAssistantError(f"Tuya feed command failed: {err}") from err
