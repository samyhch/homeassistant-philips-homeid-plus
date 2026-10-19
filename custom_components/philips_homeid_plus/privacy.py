"""Remove credentials and personal identifiers from diagnostic exports."""

from __future__ import annotations

from typing import Any

REDACTED = "**REDACTED**"
_SENSITIVE = {
    "host", "ip", "ipaddress", "address", "mac", "macaddress", "email",
    "name", "title", "friendlyname", "devicename", "serial", "serialnumber",
    "deviceid", "cppid", "externalid", "userid", "homeid", "uuid", "uid",
    "did", "id", "lanaddress", "callbackurl", "authorization", "cookie",
    "clientid", "clientsecret", "encryptionkey", "localkey", "tuyalocalkey",
    "codeverifier", "password", "passwd", "secret", "cloudrefreshtoken",
}


def redact_diagnostics(value: Any) -> Any:
    """Return a new JSON-compatible structure with sensitive values removed.

    Camera and download URLs may contain embedded credentials or signed query
    parameters. Do not export URLs, including ones in otherwise harmless lists.
    This deliberately prefers removing excess detail over exposing credentials.
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            sensitive = (
                normalized in _SENSITIVE
                or "token" in normalized
                or normalized.endswith(("password", "secret", "localkey", "url", "uri"))
            )
            result[key] = REDACTED if sensitive else redact_diagnostics(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_diagnostics(item) for item in value]
    if isinstance(value, str) and "://" in value:
        return REDACTED
    return value
