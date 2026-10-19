"""Regression tests for diagnostic exports without a running HA instance."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "philips_homeid_plus"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy = load_module("homeid_privacy", COMPONENT / "privacy.py")
util = load_module("homeid_util", COMPONENT / "util.py")


class PrivacyTests(unittest.TestCase):
    def test_nested_credentials_are_removed_without_mutating_source(self):
        source = {
            "accessToken": "access-secret",
            "properties": [{"CLIENT_SECRET": "client-secret", "pm25": 12}],
            "status": {"TuyaLocalKey": "local-secret", "power": True},
            "camera": ["rtsp://user:pass@192.0.2.1/live"],
            "callback_url": "https://example.test/?code=secret",
            "cpp_id": "device-secret",
        }
        result = privacy.redact_diagnostics(source)
        serialized = str(result)
        for secret in ("access-secret", "client-secret", "local-secret", "user:pass", "device-secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(result["properties"][0]["pm25"], 12)
        self.assertTrue(result["status"]["power"])
        self.assertEqual(source["properties"][0]["CLIENT_SECRET"], "client-secret")

    def test_personal_identifiers_and_signed_links(self):
        data = {"host": "192.0.2.1", "deviceId": "123", "email": "test@example.test",
                "nested": {"download_url": "https://example.test/?sig=secret"},
                "model": "PAW5320", "firmware": "1.2.3", "available": False}
        result = privacy.redact_diagnostics(data)
        for key in ("host", "deviceId", "email"):
            self.assertEqual(result[key], privacy.REDACTED)
        self.assertEqual(result["nested"]["download_url"], privacy.REDACTED)
        self.assertEqual(result["model"], "PAW5320")
        self.assertFalse(result["available"])


class IdentifierTests(unittest.TestCase):
    def test_mac_variants_have_one_identity(self):
        for raw in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", " AABBCCDDEEFF ",
                    "12345678-1234-1234-1234-aabbccddeeff"):
            with self.subTest(raw=raw):
                self.assertEqual(util.normalize_unique_id(raw), "aa:bb:cc:dd:ee:ff")

    def test_non_mac_identifiers_are_not_reformatted(self):
        self.assertEqual(util.normalize_unique_id("Thing-123"), "thing-123")
        self.assertEqual(util.normalize_unique_id(""), "")


class BackendDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Stub only HA imports; exercise the actual integration entry point.
        modules = {}
        for name in ("homeassistant", "homeassistant.config_entries", "homeassistant.const",
                     "homeassistant.core", "diagnostic_test", "diagnostic_test.const",
                     "diagnostic_test.coordinator"):
            modules[name] = ModuleType(name)
        modules["homeassistant.config_entries"].ConfigEntry = object
        modules["homeassistant.core"].HomeAssistant = object
        modules["homeassistant.const"].CONF_HOST = "host"
        modules["diagnostic_test.coordinator"].PhilipsHomeIDCoordinator = object
        constants = modules["diagnostic_test.const"]
        constants.DOMAIN = "philips_homeid_plus"
        for key in ("CONF_CLIENT_ID", "CONF_CLIENT_SECRET", "CONF_CLOUD_REFRESH_TOKEN",
                    "CONF_ENCRYPTION_KEY"):
            setattr(constants, key, key.removeprefix("CONF_").lower())
        modules["diagnostic_test.privacy"] = privacy
        self.imports = patch.dict(sys.modules, modules)
        self.imports.start()
        self.addCleanup(self.imports.stop)
        self.diagnostics = load_module("diagnostic_test.diagnostics", COMPONENT / "diagnostics.py")
        self.entry = SimpleNamespace(entry_id="entry", options={}, data={})

    async def test_unloaded_entry_can_export_safe_diagnostics(self):
        self.entry.data = {"cloud_refresh_token": "secret", "host": "192.0.2.1"}
        result = await self.diagnostics.async_get_config_entry_diagnostics(
            SimpleNamespace(data={}), self.entry
        )
        self.assertFalse(result["loaded"])
        self.assertNotIn("secret", str(result))
        self.assertNotIn("192.0.2.1", str(result))

    async def test_airpurifier_uses_coap_runtime_instead_of_homeid_coordinator(self):
        self.entry.data = {"is_airpurifier_coap": True, "status": {"DeviceId": "private"}}
        self.entry.options = {"host": "192.0.2.1"}
        runtime = SimpleNamespace(device_information=SimpleNamespace(model="AC3360/11"),
                                  coordinator=SimpleNamespace(status={"pm25": 7, "DeviceId": "private"}))
        hass = SimpleNamespace(data={"philips_homeid_plus": {"entry": runtime}})
        result = await self.diagnostics.async_get_config_entry_diagnostics(hass, self.entry)
        self.assertTrue(result["loaded"])
        self.assertEqual(result["backend"], "local_coap")
        self.assertEqual(result["state"]["pm25"], 7)
        self.assertNotIn("private", str(result))
        self.assertNotIn("192.0.2.1", str(result))

    async def test_airpurifier_failed_setup_has_diagnostics(self):
        self.entry.data = {"is_airpurifier_coap": True}
        result = await self.diagnostics.async_get_config_entry_diagnostics(
            SimpleNamespace(data={}), self.entry
        )
        self.assertFalse(result["loaded"])
        self.assertEqual(result["backend"], "local_coap")

    async def test_account_diagnostics_export_counts_without_credentials(self):
        self.entry.data = {"is_homeid_account": True, "cloud_refresh_token": "secret"}
        coordinator = SimpleNamespace(
            data={"discovered_devices": 3, "configured_devices": 2},
            last_update_success=True,
        )
        hass = SimpleNamespace(data={"philips_homeid_plus": {
            "entry": {"account_coordinator": coordinator},
        }})
        result = await self.diagnostics.async_get_config_entry_diagnostics(hass, self.entry)
        self.assertEqual(result["inventory"]["discovered_devices"], 3)
        self.assertTrue(result["loaded"])
        self.assertNotIn("secret", str(result))

    async def test_pet_export_excludes_camera_credentials_and_recorder_config(self):
        ha_diagnostics = ModuleType("homeassistant.components.diagnostics")
        ha_diagnostics.async_redact_data = lambda data, keys: data
        constants = ModuleType("diagnostic_test.pet_series.const")
        constants.DOMAIN = "philips_homeid_plus"
        with patch.dict(sys.modules, {
            "homeassistant.components": ModuleType("homeassistant.components"),
            "homeassistant.components.diagnostics": ha_diagnostics,
            "diagnostic_test.pet_series": ModuleType("diagnostic_test.pet_series"),
            "diagnostic_test.pet_series.const": constants,
        }):
            pet = load_module("diagnostic_test.pet_series.diagnostics",
                              COMPONENT / "pet_series" / "diagnostics.py")
        self.entry.title = "Private home"
        self.entry.data = {"accessToken": "private-token"}
        coordinator = SimpleNamespace(last_update_success=True, update_interval=30,
                                      data={"devices": [SimpleNamespace(name="Private feeder")]})
        bridge = SimpleNamespace(camera_mode="always", stream_endpoint=lambda device: {
            "url": "rtsp://user:private-password@192.0.2.1/live",
            "address_source": "local",
        })
        hass = SimpleNamespace(data={"philips_homeid_plus": {"entry": {
            "coordinator": coordinator, "bridge": bridge,
        }}})
        result = await pet.async_get_config_entry_diagnostics(hass, self.entry)
        for secret in ("private-token", "private-password", "192.0.2.1", "Private home"):
            self.assertNotIn(secret, str(result))
        self.assertNotIn("frigate_example", result["camera_streaming"])
        self.assertTrue(result["camera_streaming"]["cameras"][0]["stream_available"])
