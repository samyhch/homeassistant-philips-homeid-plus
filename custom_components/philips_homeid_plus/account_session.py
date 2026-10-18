"""Share an existing HomeID session between discovery and feeder entries."""
from __future__ import annotations

import asyncio
import time

from .cloud_api import PhilipsCloudAPI
from .const import CONF_CLOUD_REFRESH_TOKEN, CONF_OAUTH_CLIENT, DOMAIN, OAUTH_CLIENT_HOMEID


async def homeid_tokens(hass, entry):
    """Refresh once per account session; persist rotation through HA."""
    state = hass.data.setdefault(DOMAIN + "_accounts", {})
    lock = state.setdefault("lock", asyncio.Lock())
    async with lock:
        current = entry.data.get(CONF_CLOUD_REFRESH_TOKEN, "")
        if not current:
            raise RuntimeError("HomeID refresh token is missing")
        cached = state.setdefault("tokens", {})
        item = cached.get(current)
        if item and item[0] > time.monotonic():
            return item[1]
        api = PhilipsCloudAPI()
        try:
            tokens = await api.refresh_tokens(current, OAUTH_CLIENT_HOMEID)
        finally:
            await api.close()
        replacement = tokens.get("refresh_token") or current
        for other in hass.config_entries.async_entries(DOMAIN):
            if other.data.get(CONF_CLOUD_REFRESH_TOKEN) == current:
                hass.config_entries.async_update_entry(
                    other, data={**other.data, CONF_CLOUD_REFRESH_TOKEN: replacement}
                )
        ttl = max(0, min(int(tokens.get("expires_in", 300)) - 60, 3000))
        cached[replacement] = (time.monotonic() + ttl, tokens)
        if replacement != current:
            cached.pop(current, None)
        return tokens

async def inspect_homeid_account(hass, entry):
    """Check HomeID discovery once; record only non-secret capability metadata."""
    import logging
    state = hass.data.setdefault(DOMAIN + "_accounts", {})
    if state.get("discovery_checked"):
        return
    state["discovery_checked"] = True
    api = PhilipsCloudAPI()
    try:
        tokens = await homeid_tokens(hass, entry)
        appliances = await api.get_appliances_via_homeid(tokens)
        summary = [
            {
                "backend": item.get("registeredIn"),
                "fields": sorted(item),
                "relations": sorted(item.get("_links", {})),
            }
            for item in appliances if item.get("registeredIn") == "TUYA"
        ]
        state["discovery_summary"] = summary
        logging.getLogger(__name__).warning(
            "HomeID saved session verified: %d appliances; Tuya capability metadata=%s",
            len(appliances), summary,
        )
    except Exception as err:
        logging.getLogger(__name__).warning(
            "HomeID saved session discovery failed (%s)", type(err).__name__
        )
        state.pop("discovery_checked", None)
    finally:
        await api.close()
