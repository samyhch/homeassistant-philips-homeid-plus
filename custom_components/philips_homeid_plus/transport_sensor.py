"""Diagnostic entity exposing existing connection health without extra polling."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .transport import subscribe_transport, transport_diagnostics


class ConnectionHealthSensor(SensorEntity):
    _attr_name = "Connection health"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:connection"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connection_health"
        self._attr_name = f"{entry.title} connection health"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(subscribe_transport(self.hass, self.entry, self.async_write_ha_state))

    @property
    def native_value(self):
        status = transport_diagnostics(self.hass, self.entry)
        return status["reason"] or "connected"

    @property
    def extra_state_attributes(self):
        status = transport_diagnostics(self.hass, self.entry)
        return {key: status[key] for key in ("transport", "last_successful_update")}
