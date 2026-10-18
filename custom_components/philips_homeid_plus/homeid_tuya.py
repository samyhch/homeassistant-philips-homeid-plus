"""HomeID 8.22 Tuya application identity and a cached session.

Application constants come from the user-supplied official APK and are not
account credentials. User authentication remains the existing HomeID OAuth flow.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from tuya_mobile.client import TuyaMobileClient
from tuya_mobile.signer import PurePythonTuyaSigner

from .account_session import homeid_tokens
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
HOMEID_APP = {
    "app_id": "d997esphw5fevawrcyud",
    "app_secret": "fcxp5hwguv5vpa4wveu8tujnhky8nhde",
    "cert_sha256_hex": "d2d695a11d1b84f925a9456e27f445e9fd87c37463aa8a3432a66a233b0fd50f",
    "app_key": "dgsgxpwew54gdpcm5cuqfrvjpakxgvmn",
    "package": "com.philips.ka.oneka.app",
}


class HomeIDTuyaSession:
    """Serialize requests and reuse the same Tuya session until it expires."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.lock = asyncio.Lock()
        self.client = None
        self.installation_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, entry.entry_id))

    async def call(self, action, payload, *, version="1.0"):
        async with self.lock:
            if self.client is None:
                tokens = await homeid_tokens(self.hass, self.entry)
                client = TuyaMobileClient(
                    PurePythonTuyaSigner(**HOMEID_APP),
                    async_get_clientsession(self.hass),
                    device_id=self.installation_id,
                )
                client.APP_VERSION = "8.22.0"
                login = await client.login_with_jwt(tokens["id_token"], "359", "PhilipsDA")
                client.partner_id = login.get("partnerIdentity") or login.get("partnerId")
                _LOGGER.debug("HomeID Tuya login fields=%s; partner identity present=%s",
                              sorted(login), bool(client.partner_id))
                self.client = client
            try:
                result = await self.client._call(action, payload, version=version)
            except RuntimeError as err:
                if any(code in str(err) for code in ("USER_SESSION_INVALID", "SESSION_INVALID", "USER_SESSION_EXPIRED")):
                    self.client = None
                raise
            if result.get("success") is False or result.get("errorCode") or result.get("errorMsg"):
                code = str(result.get("errorCode") or "unknown")
                if code in {"USER_SESSION_INVALID", "SESSION_INVALID", "USER_SESSION_EXPIRED"}:
                    self.client = None
                # Never retry a device write: the server may have applied it.
                raise RuntimeError(f"HomeID Tuya {action}: {code}")
            return result

    async def status(self, device_id):
        return await self.call("s.m.dev.dp.get", {"devId": device_id, "gwId": device_id})

    async def publish(self, device_id, dps):
        return await self.call(
            "thing.m.device.dp.publish",
            {"devId": device_id, "gwId": device_id,
             "dps": json.dumps(dps, separators=(",", ":"))},
        )


def session_for(hass, entry):
    sessions = hass.data.setdefault(DOMAIN + "_tuya_sessions", {})
    return sessions.setdefault(entry.entry_id, HomeIDTuyaSession(hass, entry))


async def verify_device_access(hass, entry):
    """Read device status only. Do not publish DPs or start a camera."""
    try:
        status = await session_for(hass, entry).status(entry.data["tuya_device_id"])
        _LOGGER.warning("HomeID Tuya access verified for %s: status keys=%s", entry.title, sorted(status))
    except Exception as err:
        _LOGGER.warning("HomeID Tuya access verification for %s failed: %s", entry.title, err)
