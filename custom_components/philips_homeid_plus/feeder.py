"""Experimental Philips Pet Series feeder cloud support."""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

def tuya_device_id(device: Any) -> str:
    """Resolve the Tuya device ID using the Philips integration convention."""
    value = (
        getattr(device, "vendor_id", None)
        or getattr(device, "external_id", None)
        or getattr(device, "id", None)
    )
    if not value:
        raise ValueError("Philips feeder has no Tuya device ID")
    return str(value)


async def feed_once(client: Any, device: Any) -> None:
    """Send one experimental feed command through Tuya Cloud."""
    model = str(
        getattr(device, "product_ctn", "")
        or getattr(device, "model", "")
    ).upper()

    if model.startswith("PAW3320"):
        dp_id = "101"
    elif model.startswith("PAW5320"):
        dp_id = "201"
    else:
        raise ValueError(f"Unsupported feeder model: {model or 'unknown'}")

    if not getattr(getattr(client, "auth", None), "id_token", None):
        raise RuntimeError("Missing ID token for Tuya Cloud authentication")

    device_id = tuya_device_id(device)
    _LOGGER.info("Sending experimental feed command using DP %s", dp_id)
    await client.publish_cloud_dps(device_id, {dp_id: 1.0})
