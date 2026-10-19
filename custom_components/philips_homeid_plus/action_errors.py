"""Translate known vendor failures without exposing raw responses or retrying actions."""
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


def error_key(error):
    """Classify conservatively; permission denied is not proof of expired login."""
    code = str(getattr(error, "code", "") or error).upper()
    if isinstance(error, (TimeoutError, ConnectionError)) or any(
        token in code for token in ("DEVICE_OFFLINE", "DEVICE OFFLINE", "UNREACHABLE")
    ):
        return "device_offline"
    if any(token in code for token in ("TOKEN_EXPIRED", "SESSION_EXPIRED", "INVALID_TOKEN")):
        return "auth_expired"
    if "PERMISSION_DENIED" in code:
        return "permission_denied"
    if any(token in code for token in ("NOT_SUPPORTED", "UNSUPPORTED")):
        return "command_unsupported"
    if any(token in code for token in ("FOOD_OUTLET_STUCK", "FOOD_LEVEL_LOW")):
        return "feeding_problem"
    return "command_failed"


def action_error(error):
    """Keep the original exception as a cause, not as user-visible text."""
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=error_key(error))
