"""HomeID account inventory and management using the existing OTP session."""

from __future__ import annotations

from datetime import timedelta
import logging

import aiohttp
from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .account_session import homeid_tokens
from .cloud_api import CloudAuthError, CloudConnectionError, PhilipsCloudAPI
from .const import CONF_CLOUD_REFRESH_TOKEN, CONF_OAUTH_CLIENT, DOMAIN, OAUTH_CLIENT_HOMEID

_LOGGER = logging.getLogger(__name__)


def linked_device_count(entries, account_entry):
    """Count existing entries sharing this session without changing identities."""
    token = account_entry.data.get(CONF_CLOUD_REFRESH_TOKEN)
    if not token:
        return 0
    return sum(
        1 for entry in entries
        if not entry.data.get("is_homeid_account")
        and entry.data.get(CONF_CLOUD_REFRESH_TOKEN) == token
        and entry.data.get(CONF_OAUTH_CLIENT, OAUTH_CLIENT_HOMEID) == OAUTH_CLIENT_HOMEID
    )


class HomeIDAccountCoordinator(DataUpdateCoordinator):
    """Fetch account inventory, retaining credentials only in config entries."""

    def __init__(self, hass, entry):
        super().__init__(
            hass, _LOGGER, name="HomeID account", config_entry=entry,
            update_interval=timedelta(minutes=getattr(entry, "options", {}).get("inventory_interval", 15)),
        )
        self.entry = entry

    async def _async_update_data(self):
        api = PhilipsCloudAPI()
        try:
            tokens = await homeid_tokens(self.hass, self.entry)
            appliances = await api.get_appliances_via_homeid(tokens)
            if not appliances:
                appliances = await api.get_devices(tokens["access_token"])
            return {
                "discovered_devices": len(appliances),
                "configured_devices": linked_device_count(
                    self.hass.config_entries.async_entries(DOMAIN), self.entry
                ),
            }
        except (CloudConnectionError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed("The HomeID account inventory is temporarily unreachable") from err
        except CloudAuthError as err:
            raise ConfigEntryAuthFailed("The HomeID account session expired") from err
        finally:
            await api.close()


async def async_setup_entry(hass, entry):
    """Set up account diagnostics without touching existing device entries."""
    coordinator = HomeIDAccountCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"account_coordinator": coordinator}
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except BaseException:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await coordinator.async_shutdown()
        raise
    return True


async def async_unload_entry(hass, entry):
    """Stop polling after the account entities have unloaded."""
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return False
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime:
        await runtime["account_coordinator"].async_shutdown()
    return True


class HomeIDAccountOptionsFlow(config_entries.OptionsFlow):
    """Refresh inventory or start device onboarding with the saved account."""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="account", menu_options=["add_device", "refresh", "settings"])

    async def async_step_settings(self, user_input=None):
        """Adjust account inventory polling, not appliance command frequency."""
        import voluptuous as vol

        errors = {}
        if user_input is not None:
            interval = user_input.get("inventory_interval")
            if type(interval) is not int or not 1 <= interval <= 60:
                errors["base"] = "invalid_inventory_interval"
            else:
                runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
                if runtime:
                    runtime["account_coordinator"].update_interval = timedelta(minutes=interval)
                return self.async_create_entry(data={**self.config_entry.options, "inventory_interval": interval}, title="")
        return self.async_show_form(step_id="settings", errors=errors, data_schema=vol.Schema({
            vol.Required("inventory_interval", default=self.config_entry.options.get("inventory_interval", 15)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        }))

    async def async_step_add_device(self, user_input=None):
        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"account_entry_id": self.config_entry.entry_id},
        )
        return self.async_abort(reason="account_discovery_started")

    async def async_step_refresh(self, user_input=None):
        runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if not runtime:
            return self.async_abort(reason="account_not_loaded")
        coordinator = runtime["account_coordinator"]
        await coordinator.async_request_refresh()
        return self.async_abort(
            reason="account_refreshed" if coordinator.last_update_success else "account_refresh_failed"
        )
