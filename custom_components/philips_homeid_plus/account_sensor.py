"""Diagnostic counts for a centrally managed HomeID account."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["account_coordinator"]
    async_add_entities([
        HomeIDAccountSensor(coordinator, entry, key)
        for key in ("discovered_devices", "configured_devices")
    ])


class HomeIDAccountSensor(CoordinatorEntity, SensorEntity):
    """Expose inventory counts, never account credentials or device lists."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:devices"

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id)},
            "name": entry.title,
            "manufacturer": "Philips",
            "model": "HomeID account",
        }

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)
