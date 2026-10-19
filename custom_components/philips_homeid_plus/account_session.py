"""Share an existing HomeID session between discovery and feeder entries."""
from __future__ import annotations

import asyncio
import time

from .cloud_api import PhilipsCloudAPI
from .const import CONF_CLOUD_REFRESH_TOKEN, CONF_OAUTH_CLIENT, DOMAIN, OAUTH_CLIENT_HOMEID


def saved_homeid_sessions(entries):
    """Return one representative entry per HomeID refresh-token family.

    Entries remain per-device, so choosing a saved session never migrates entity
    or device registry identities. Air+ tokens have a different OAuth audience.
    """
    seen = set()
    sessions = []
    for entry in sorted(entries, key=lambda item: not item.data.get("is_homeid_account")):
        token = entry.data.get(CONF_CLOUD_REFRESH_TOKEN)
        if (
            token
            and token not in seen
            and entry.data.get(CONF_OAUTH_CLIENT, OAUTH_CLIENT_HOMEID) == OAUTH_CLIENT_HOMEID
        ):
            seen.add(token)
            sessions.append(entry)
    return sessions


async def homeid_tokens(hass, entry):
    """Refresh once per account session; persist rotation through HA."""
    state = hass.data.setdefault(DOMAIN + "_accounts", {})
    lock = state.setdefault("lock", asyncio.Lock())
    async with lock:
        if entry.data.get(CONF_OAUTH_CLIENT, OAUTH_CLIENT_HOMEID) != OAUTH_CLIENT_HOMEID:
            raise ValueError("A non-HomeID session cannot be refreshed as HomeID")
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
            return _persist_tokens(hass, state, current, tokens)
        finally:
            await api.close()


def _persist_tokens(hass, state, current, response):
    """Persist rotation before awaiting HTTP cleanup, even during cancellation."""
    tokens = {**response, "refresh_token": response.get("refresh_token") or current}
    replacement = tokens["refresh_token"]
    for other in hass.config_entries.async_entries(DOMAIN):
        if (
            other.data.get(CONF_CLOUD_REFRESH_TOKEN) == current
            and other.data.get(CONF_OAUTH_CLIENT, OAUTH_CLIENT_HOMEID) == OAUTH_CLIENT_HOMEID
        ):
            if replacement != current:
                hass.config_entries.async_update_entry(
                    other, data={**other.data, CONF_CLOUD_REFRESH_TOKEN: replacement}
                )
    try:
        lifetime = int(tokens.get("expires_in", 300))
    except (ValueError, TypeError):
        lifetime = 0
    ttl = max(0, min(lifetime - 60, 3000))
    cached = state.setdefault("tokens", {})
    cached[replacement] = (time.monotonic() + ttl, tokens)
    if replacement != current:
        cached.pop(current, None)
    return tokens


def save_reauthenticated_session(hass, entry, tokens):
    """Replace a shared HomeID session after the existing email/OTP flow."""
    if entry.data.get(CONF_OAUTH_CLIENT, OAUTH_CLIENT_HOMEID) != OAUTH_CLIENT_HOMEID:
        raise ValueError("Cannot replace another OAuth audience as HomeID")
    state = hass.data.setdefault(DOMAIN + "_accounts", {})
    current = entry.data.get(CONF_CLOUD_REFRESH_TOKEN, "")
    if not current or not tokens.get("refresh_token"):
        raise ValueError("A complete HomeID refresh session is required")
    return _persist_tokens(hass, state, current, tokens)

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
