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
