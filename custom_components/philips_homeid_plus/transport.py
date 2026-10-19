"""Read-only transport health; never open a second connection or invent fallback."""
from datetime import datetime, timezone

from .const import DOMAIN


def transport_kind(data):
    if data.get("is_airpurifier_coap"):
        return "local_coap"
    if data.get("is_tuya_pet"):
        return "homeid_tuya_cloud"
    if data.get("is_homeid_account"):
        return "homeid_cloud_inventory"
    if data.get("is_fusion"):
        return "cloud_mqtt_websocket"
    return "local_homeid"


def track_transport(hass, entry):
    """Track existing coordinator callbacks and clean up on unload."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    coordinator = (runtime.get("coordinator") or runtime.get("account_coordinator")) if isinstance(runtime, dict) else getattr(runtime, "coordinator", runtime)
    state = {"transport": transport_kind(entry.data), "last_successful_update": None,
             "available": None, "reason": "awaiting_update", "automatic_local_fallback": False}
    states = hass.data.setdefault(DOMAIN + "_transport", {})
    states[entry.entry_id] = state

    def updated():
        success = getattr(coordinator, "last_update_success", None)
        if success is None:
            return
        state["available"] = bool(success)
        state["reason"] = None if success else "transport_update_failed"
        if success:
            stamp = getattr(coordinator, "last_successful_update", None)
            state["last_successful_update"] = stamp or datetime.now(timezone.utc).isoformat()

    if coordinator is not None:
        updated()
        add_listener = getattr(coordinator, "async_add_listener", None)
        if add_listener:
            entry.async_on_unload(add_listener(updated))
    entry.async_on_unload(lambda: states.pop(entry.entry_id, None))


def transport_diagnostics(hass, entry):
    """Return only transport facts; do not export exceptions, addresses or tokens."""
    return dict(hass.data.get(DOMAIN + "_transport", {}).get(entry.entry_id) or {
        "transport": transport_kind(entry.data), "available": False,
        "reason": "entry_not_loaded", "last_successful_update": None,
        "automatic_local_fallback": False,
    })
