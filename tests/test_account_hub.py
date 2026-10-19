"""Account inventory, lifecycle and management regression tests."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class CoordinatorStub:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass
        self.data = None
        self.last_update_success = True
        self.async_shutdown = AsyncMock()

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()


class OptionsStub:
    def async_show_form(self, **kwargs):
        return kwargs

    def async_create_entry(self, **kwargs):
        return kwargs

    def async_show_menu(self, **kwargs):
        return kwargs

    def async_abort(self, **kwargs):
        return kwargs


class AccountHubTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = (
            "homeassistant", "homeassistant.config_entries", "homeassistant.const",
            "homeassistant.exceptions", "homeassistant.helpers",
            "homeassistant.helpers.update_coordinator", "aiohttp", "hub_test",
            "hub_test.const", "hub_test.cloud_api", "hub_test.account_session",
        )
        modules = {name: ModuleType(name) for name in names}
        config = modules["homeassistant.config_entries"]
        config.OptionsFlow = OptionsStub
        config.SOURCE_INTEGRATION_DISCOVERY = "integration_discovery"
        modules["homeassistant"].config_entries = config
        modules["homeassistant.const"].Platform = SimpleNamespace(SENSOR="sensor")
        self.auth_error = type("ConfigEntryAuthFailed", (Exception,), {})
        modules["homeassistant.exceptions"].ConfigEntryAuthFailed = self.auth_error
        self.update_error = type("UpdateFailed", (Exception,), {})
        modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = CoordinatorStub
        modules["homeassistant.helpers.update_coordinator"].UpdateFailed = self.update_error
        modules["aiohttp"].ClientError = type("ClientError", (Exception,), {})
        self.cloud = modules["hub_test.cloud_api"]
        self.cloud.CloudAuthError = type("CloudAuthError", (Exception,), {})
        self.cloud.CloudConnectionError = type("CloudConnectionError", (self.cloud.CloudAuthError,), {})
        self.api = SimpleNamespace(
            get_appliances_via_homeid=AsyncMock(return_value=[{"name": "Example"}]),
            get_devices=AsyncMock(return_value=[]), close=AsyncMock(),
        )
        self.cloud.PhilipsCloudAPI = Mock(return_value=self.api)
        self.tokens = AsyncMock(return_value={"access_token": "access", "refresh_token": "refresh"})
        modules["hub_test.account_session"].homeid_tokens = self.tokens
        constants = modules["hub_test.const"]
        constants.CONF_CLOUD_REFRESH_TOKEN = "cloud_refresh_token"
        constants.CONF_OAUTH_CLIENT = "oauth_client"
        constants.DOMAIN = "philips_homeid_plus"
        constants.OAUTH_CLIENT_HOMEID = "homeid"
        self.imports = patch.dict(sys.modules, modules)
        self.imports.start()
        self.addCleanup(self.imports.stop)
        path = (Path(__file__).resolve().parents[1] / "custom_components"
                / "philips_homeid_plus" / "account_hub.py")
        spec = importlib.util.spec_from_file_location("hub_test.account_hub", path)
        self.hub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hub)
        self.entry = SimpleNamespace(entry_id="hub", data={
            "is_homeid_account": True, "cloud_refresh_token": "refresh",
        }, options={})
        self.device = SimpleNamespace(data={"cloud_refresh_token": "refresh"})
        self.hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_entries=Mock(return_value=[self.entry, self.device]),
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
                flow=SimpleNamespace(async_init=AsyncMock()),
            ),
        )

    async def test_inventory_returns_only_counts_and_closes_client(self):
        coordinator = self.hub.HomeIDAccountCoordinator(self.hass, self.entry)
        result = await coordinator._async_update_data()
        self.assertEqual(result, {"discovered_devices": 1, "configured_devices": 1})
        self.assertNotIn("refresh", str(result))
        self.api.close.assert_awaited_once()

    async def test_empty_inventory_uses_registry_fallback(self):
        self.api.get_appliances_via_homeid.return_value = []
        self.api.get_devices.return_value = [{"id": "one"}, {"id": "two"}]
        result = await self.hub.HomeIDAccountCoordinator(self.hass, self.entry)._async_update_data()
        self.assertEqual(result["discovered_devices"], 2)
        self.api.get_devices.assert_awaited_once_with("access")

    async def test_empty_account_is_valid(self):
        self.api.get_appliances_via_homeid.return_value = []
        result = await self.hub.HomeIDAccountCoordinator(self.hass, self.entry)._async_update_data()
        self.assertEqual(result["discovered_devices"], 0)

    async def test_transient_error_is_not_reauthentication(self):
        self.tokens.side_effect = self.cloud.CloudConnectionError()
        with self.assertRaises(self.update_error):
            await self.hub.HomeIDAccountCoordinator(self.hass, self.entry)._async_update_data()
        self.api.close.assert_awaited_once()

    async def test_rejected_session_requests_reauthentication(self):
        self.tokens.side_effect = self.cloud.CloudAuthError()
        with self.assertRaises(self.auth_error):
            await self.hub.HomeIDAccountCoordinator(self.hass, self.entry)._async_update_data()
        self.api.close.assert_awaited_once()

    def test_count_excludes_other_accounts_and_oauth_audiences(self):
        entries = [self.entry, self.device,
                   SimpleNamespace(data={"cloud_refresh_token": "other"}),
                   SimpleNamespace(data={"cloud_refresh_token": "refresh", "oauth_client": "airplus"})]
        self.assertEqual(self.hub.linked_device_count(entries, self.entry), 1)

    async def test_setup_and_unload_forward_only_account_sensors(self):
        self.assertTrue(await self.hub.async_setup_entry(self.hass, self.entry))
        self.hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            self.entry, ["sensor"]
        )
        coordinator = self.hass.data["philips_homeid_plus"]["hub"]["account_coordinator"]
        self.assertTrue(await self.hub.async_unload_entry(self.hass, self.entry))
        coordinator.async_shutdown.assert_awaited_once()
        self.assertNotIn("hub", self.hass.data["philips_homeid_plus"])

    async def test_failed_platform_setup_removes_runtime_and_shuts_down(self):
        self.hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("platform")
        coordinator = self.hub.HomeIDAccountCoordinator(self.hass, self.entry)
        with patch.object(self.hub, "HomeIDAccountCoordinator", return_value=coordinator):
            with self.assertRaisesRegex(RuntimeError, "platform"):
                await self.hub.async_setup_entry(self.hass, self.entry)
        coordinator.async_shutdown.assert_awaited_once()
        self.assertNotIn("hub", self.hass.data["philips_homeid_plus"])

    async def test_failed_unload_retains_runtime(self):
        await self.hub.async_setup_entry(self.hass, self.entry)
        self.hass.config_entries.async_unload_platforms.return_value = False
        self.assertFalse(await self.hub.async_unload_entry(self.hass, self.entry))
        self.assertIn("hub", self.hass.data["philips_homeid_plus"])

    async def test_add_device_starts_flow_with_only_the_account_reference(self):
        options = self.hub.HomeIDAccountOptionsFlow()
        options.hass = self.hass
        options.config_entry = self.entry
        result = await options.async_step_add_device()
        self.assertEqual(result["reason"], "account_discovery_started")
        self.hass.config_entries.flow.async_init.assert_awaited_once_with(
            "philips_homeid_plus", context={"source": "integration_discovery"},
            data={"account_entry_id": "hub"},
        )

    async def test_inventory_interval_options_validate_and_apply_without_reload(self):
        from datetime import timedelta
        vol = ModuleType("voluptuous")
        vol.Schema = lambda value: value
        vol.Required = lambda key, **kwargs: key
        vol.All = lambda *args: args
        vol.Coerce = lambda value: value
        vol.Range = lambda **kwargs: kwargs
        options = self.hub.HomeIDAccountOptionsFlow()
        options.hass = self.hass
        options.config_entry = self.entry
        self.entry.options = {"unrelated_option": True}
        coordinator = SimpleNamespace(update_interval=timedelta(minutes=15))
        self.hass.data["philips_homeid_plus"] = {"hub": {"account_coordinator": coordinator}}
        with patch.dict(sys.modules, {"voluptuous": vol}):
            for value in (0, 61, 2.5, True, "5"):
                result = await options.async_step_settings({"inventory_interval": value})
                self.assertEqual(result["errors"]["base"], "invalid_inventory_interval")
            result = await options.async_step_settings({"inventory_interval": 5})
        self.assertEqual(result["data"], {"unrelated_option": True, "inventory_interval": 5})
        self.assertEqual(coordinator.update_interval, timedelta(minutes=5))
