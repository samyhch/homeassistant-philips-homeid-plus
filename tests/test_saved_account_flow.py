"""Exercise the real saved-account flow with external imports stubbed.

These tests verify routing and error handling, not HA form rendering or schema
validation. Import boundaries are stubbed so the suite runs without HA installed.
"""

import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "philips_homeid_plus"


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SavedAccountFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = [
            "homeassistant", "homeassistant.config_entries", "homeassistant.const",
            "homeassistant.core", "homeassistant.helpers", "homeassistant.helpers.selector",
            "homeassistant.helpers.service_info", "homeassistant.helpers.service_info.ssdp",
            "homeassistant.helpers.service_info.zeroconf", "aiohttp", "voluptuous",
            "flow_test", "flow_test.cloud_api", "flow_test.const", "flow_test.local_api",
            "flow_test.sensor_descriptions",
        ]
        modules = {name: ModuleType(name) for name in names}
        config_entries = modules["homeassistant.config_entries"]
        config_entries.ConfigFlow = FlowBase
        config_entries.OptionsFlow = FlowBase
        config_entries.ConfigFlowResult = dict
        modules["homeassistant"].config_entries = config_entries
        modules["homeassistant.const"].CONF_HOST = "host"
        modules["homeassistant.const"].CONF_NAME = "name"
        modules["homeassistant.core"].callback = lambda function: function
        vol = modules["voluptuous"]
        vol.Schema = lambda schema: schema
        vol.Required = lambda key, **kwargs: key
        vol.Optional = lambda key, **kwargs: key
        vol.In = lambda choices: choices
        modules["aiohttp"].ClientError = type("ClientError", (Exception,), {})

        # Create import placeholders from the actual import declarations. The
        # session/config-flow implementations themselves are loaded unchanged.
        tree = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                name = ("flow_test." + node.module) if node.level else node.module
                if name in modules:
                    for alias in node.names:
                        if not hasattr(modules[name], alias.name):
                            setattr(modules[name], alias.name, Mock())
        constants = modules["flow_test.const"]
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "const" and node.level:
                for alias in node.names:
                    setattr(constants, alias.name, alias.name.removeprefix("CONF_").lower())
        constants.DOMAIN = "philips_homeid_plus"
        constants.OAUTH_CLIENT_HOMEID = "homeid"
        constants.OAUTH_CLIENT_AIRPLUS = "airplus"
        cloud = modules["flow_test.cloud_api"]
        cloud.CloudAuthError = type("CloudAuthError", (Exception,), {})
        cloud.CloudConnectionError = type("CloudConnectionError", (cloud.CloudAuthError,), {})
        cloud.CloudBackendError = type("CloudBackendError", (cloud.CloudConnectionError,), {})
        cloud.CloudNotRegisteredError = type("CloudNotRegisteredError", (cloud.CloudAuthError,), {})
        self.api = SimpleNamespace(
            close=AsyncMock(),
            get_appliances_via_homeid=AsyncMock(return_value=[{"name": "Example feeder"}]),
        )
        cloud.PhilipsCloudAPI = Mock(return_value=self.api)
        self.cloud = cloud
        self.imports = patch.dict(sys.modules, modules)
        self.imports.start()
        self.addCleanup(self.imports.stop)
        sys.modules["flow_test.util"] = load_module("flow_test.util", COMPONENT / "util.py")
        self.sessions = load_module("flow_test.account_session", COMPONENT / "account_session.py")
        sys.modules["flow_test.account_session"] = self.sessions
        self.tokens = {"access_token": "example-access", "refresh_token": "example-refresh"}
        self.sessions.homeid_tokens = AsyncMock(return_value=self.tokens)
        self.module = load_module("flow_test.config_flow", COMPONENT / "config_flow.py")
        self.flow = self.module.PhilipsHomeIDConfigFlow()
        self.entries = [
            SimpleNamespace(entry_id="first", title="First feeder",
                            data={"cloud_refresh_token": "first-token"}),
            SimpleNamespace(entry_id="second", title="Second feeder",
                            data={"cloud_refresh_token": "first-token"}),
            SimpleNamespace(entry_id="another", title="Another account",
                            data={"cloud_refresh_token": "another-token"}),
        ]
        self.flow.hass = SimpleNamespace()
        self.flow._async_current_entries = lambda: self.entries
        self.flow._discover_iot_devices = AsyncMock(return_value=[])
        self.flow.async_step_cloud_devices = AsyncMock(return_value={"type": "device_selection"})

    async def test_existing_login_routes_to_deduplicated_session_choice(self):
        result = await self.flow.async_step_cloud_email()
        self.assertEqual(result["step_id"], "saved_account")
        options = result["data_schema"]["account"]
        self.assertEqual(set(options), {"first", "another", "new_login"})
        self.sessions.homeid_tokens.assert_not_awaited()

    async def test_selected_account_not_first_account_supplies_discovery(self):
        result = await self.flow.async_step_saved_account({"account": "another"})
        self.assertEqual(result["type"], "device_selection")
        self.sessions.homeid_tokens.assert_awaited_once_with(self.flow.hass, self.entries[2])
        self.api.get_appliances_via_homeid.assert_awaited_once_with(self.tokens)
        self.flow._discover_iot_devices.assert_not_awaited()
        self.api.close.assert_not_awaited()

    async def test_new_login_opens_existing_email_flow_without_recursing(self):
        self.flow._cloud_api = self.api
        self.flow._cloud_tokens = {"refresh_token": "previous"}
        self.flow._cloud_devices = [("homeid", {"name": "Previous account device"})]
        result = await self.flow.async_step_saved_account({"account": "new_login"})
        self.assertEqual(result["step_id"], "cloud_email")
        self.assertEqual(result["errors"], {})
        self.sessions.homeid_tokens.assert_not_awaited()
        self.api.close.assert_awaited_once()
        self.assertEqual(self.flow._cloud_tokens, {})
        self.assertEqual(self.flow._cloud_devices, [])

    async def test_removed_account_returns_form_without_network(self):
        result = await self.flow.async_step_saved_account({"account": "removed"})
        self.assertEqual(result["step_id"], "saved_account")
        self.assertEqual(result["errors"], {"base": "unknown"})
        self.sessions.homeid_tokens.assert_not_awaited()

    async def test_no_homeid_devices_uses_iot_fallback(self):
        self.api.get_appliances_via_homeid.return_value = []
        self.flow._discover_iot_devices.return_value = [{"thingName": "example"}]
        result = await self.flow.async_step_saved_account({"account": "first"})
        self.assertEqual(result["type"], "device_selection")
        self.assertEqual(self.flow._cloud_devices, [("iot", {"thingName": "example"})])

    async def test_empty_discovery_is_not_reported_as_bad_login(self):
        self.api.get_appliances_via_homeid.return_value = []
        result = await self.flow.async_step_saved_account({"account": "first"})
        self.assertEqual(result["errors"], {"base": "no_cloud_devices"})
        self.api.close.assert_awaited_once()
        self.assertIsNone(self.flow._cloud_api)

    async def test_expired_session_has_actionable_error_and_closes_client(self):
        self.sessions.homeid_tokens.side_effect = self.cloud.CloudAuthError()
        result = await self.flow.async_step_saved_account({"account": "first"})
        self.assertEqual(result["errors"], {"base": "saved_session_expired"})
        self.api.close.assert_awaited_once()

    async def test_transient_failure_does_not_ask_for_new_credentials(self):
        self.sessions.homeid_tokens.side_effect = self.cloud.CloudConnectionError()
        result = await self.flow.async_step_saved_account({"account": "first"})
        self.assertEqual(result["errors"], {"base": "cloud_unreachable"})
        self.api.close.assert_awaited_once()

    async def test_account_manager_uses_live_token_without_changing_devices(self):
        self.flow._saved_account_entry_id = "first"
        self.flow._cloud_tokens = {"refresh_token": "stale"}
        self.flow._set_unique_id_or_abort = AsyncMock()
        before = [dict(entry.data) for entry in self.entries]
        result = await self.flow.async_step_account_hub({"name": "My HomeID"})
        self.assertEqual(result["type"], "create_entry")
        self.assertTrue(result["data"]["is_homeid_account"])
        self.assertEqual(result["data"]["cloud_refresh_token"], "first-token")
        self.assertEqual(result["title"], "My HomeID")
        self.assertEqual([entry.data for entry in self.entries], before)
        self.assertTrue(self.flow._set_unique_id_or_abort.call_args.args[0].startswith("homeid_account_"))

    async def test_account_manager_duplicate_is_rejected(self):
        self.flow._saved_account_entry_id = "first"
        self.entries.append(SimpleNamespace(
            entry_id="hub", data={"is_homeid_account": True, "cloud_refresh_token": "first-token"}
        ))
        result = await self.flow.async_step_account_hub({"name": "Duplicate"})
        self.assertEqual(result, {"type": "abort", "reason": "already_configured"})

    async def test_removed_source_cannot_create_hub_with_stale_dialog_token(self):
        self.flow._saved_account_entry_id = "removed"
        self.flow._cloud_tokens = {"refresh_token": "old-token"}
        result = await self.flow.async_step_account_hub({"name": "Stale"})
        self.assertEqual(result["reason"], "cloud_credentials_not_found")

    async def test_account_manager_requires_name_and_token(self):
        self.flow._cloud_tokens = {"refresh_token": "first-token"}
        result = await self.flow.async_step_account_hub({"name": " "})
        self.assertEqual(result["errors"], {"base": "account_name_required"})
        self.flow._cloud_tokens = {}
        result = await self.flow.async_step_account_hub({"name": "Missing"})
        self.assertEqual(result["reason"], "cloud_credentials_not_found")

    async def test_account_discovery_rejects_other_domains_and_disabled_entries(self):
        registry = SimpleNamespace(async_get_entry=Mock())
        self.flow.hass.config_entries = registry
        for entry in (
            None,
            SimpleNamespace(domain="another", data={"is_homeid_account": True}, disabled_by=None),
            SimpleNamespace(domain="philips_homeid_plus", data={}, disabled_by=None),
            SimpleNamespace(domain="philips_homeid_plus",
                            data={"is_homeid_account": True}, disabled_by="user"),
        ):
            registry.async_get_entry.return_value = entry
            result = await self.flow.async_step_integration_discovery({"account_entry_id": "hub"})
            self.assertEqual(result["reason"], "account_unavailable")

    async def test_account_discovery_routes_to_requested_hub(self):
        entry = SimpleNamespace(entry_id="hub", domain="philips_homeid_plus",
                                data={"is_homeid_account": True}, disabled_by=None)
        self.flow.hass.config_entries = SimpleNamespace(async_get_entry=Mock(return_value=entry))
        self.flow.async_step_saved_account = AsyncMock(return_value={"type": "device_selection"})
        result = await self.flow.async_step_integration_discovery({"account_entry_id": "hub"})
        self.assertEqual(result["type"], "device_selection")
        self.flow.async_step_saved_account.assert_awaited_once_with({"account": "hub"})

    async def test_otp_email_validation_and_delivery(self):
        self.api.request_otp = AsyncMock(return_value="fixture-vtoken")
        result = await self.flow.async_step_cloud_email({"email": " "})
        self.assertEqual(result["errors"]["base"], "missing_email")
        self.api.request_otp.assert_not_awaited()
        result = await self.flow.async_step_cloud_email({"email": " fixture@example.invalid "})
        self.assertEqual(result["step_id"], "cloud_otp")
        self.api.request_otp.assert_awaited_once_with("fixture@example.invalid")

    async def test_otp_delivery_outage_closes_client(self):
        self.api.request_otp = AsyncMock(side_effect=self.cloud.CloudConnectionError("fixture outage"))
        result = await self.flow.async_step_cloud_email({"email": "fixture@example.invalid"})
        self.assertEqual(result["errors"]["base"], "cloud_unreachable")
        self.api.close.assert_awaited_once()

    async def test_otp_invalid_code_and_outage_are_distinct_and_retryable(self):
        self.flow._cloud_api = self.api
        self.flow._cloud_email = "fixture@example.invalid"
        self.flow._cloud_vtoken = "fixture"
        for exception, expected in ((self.cloud.CloudConnectionError, "cloud_unreachable"),
                                    (self.cloud.CloudAuthError, "otp_failed"),
                                    (self.cloud.CloudNotRegisteredError, "account_not_registered")):
            self.api.verify_otp = AsyncMock(side_effect=exception("fixture"))
            result = await self.flow.async_step_cloud_otp({"code": "123456"})
            self.assertEqual(result["errors"]["base"], expected)
            self.assertIs(self.flow._cloud_api, self.api)
        self.api.close.assert_not_awaited()

    async def test_consumed_otp_is_not_verified_again_on_exchange_retry(self):
        self.flow._cloud_api = self.api
        self.flow._cloud_session_token = "fixture-session"
        self.api.verify_otp = AsyncMock()
        self.api.get_oidc_tokens = AsyncMock(side_effect=self.cloud.CloudConnectionError("fixture"))
        result = await self.flow.async_step_cloud_otp({"code": ""})
        self.assertEqual(result["errors"]["base"], "cloud_unreachable")
        self.api.verify_otp.assert_not_awaited()
        self.api.get_oidc_tokens.assert_awaited_once_with("fixture-session")

    async def test_reauth_missing_entry_aborts_without_minting_tokens(self):
        self.flow._cloud_api = self.api
        self.flow._cloud_email = "fixture@example.invalid"
        self.flow._cloud_vtoken = "fixture"
        self.flow.context = {"entry_id": "gone"}
        self.flow.hass.config_entries = SimpleNamespace(async_get_entry=Mock(return_value=None))
        self.api.verify_otp = AsyncMock(return_value="fixture-session")
        self.api.get_oidc_tokens = AsyncMock()
        result = await self.flow.async_step_reauth_otp({"code": "123456"})
        self.assertEqual(result["reason"], "reauth_entry_missing")
        self.api.get_oidc_tokens.assert_not_awaited()

    async def test_reauth_preserves_airplus_audience(self):
        self.flow._cloud_api = self.api
        self.flow._cloud_email = "fixture@example.invalid"
        self.flow._cloud_vtoken = "fixture"
        self.flow.context = {"entry_id": "airplus"}
        entry = SimpleNamespace(data={"oauth_client": "airplus"})
        self.flow.hass.config_entries = SimpleNamespace(async_get_entry=Mock(return_value=entry))
        self.api.verify_otp = AsyncMock(return_value="fixture-session")
        self.api.get_oidc_tokens = AsyncMock(return_value={"refresh_token": "fixture-new"})
        self.flow.async_update_reload_and_abort = Mock(return_value={"reason": "reauth_successful"})
        result = await self.flow.async_step_reauth_otp({"code": "123456"})
        self.assertEqual(result["reason"], "reauth_successful")
        self.api.get_oidc_tokens.assert_awaited_once_with("fixture-session", client="airplus")
