"""Transport lifecycle and translated errors without live clients."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus"


def load(name):
    spec = importlib.util.spec_from_file_location(f"health_test.{name}", COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HealthTests(unittest.TestCase):
    def setUp(self):
        modules = {name: ModuleType(name) for name in (
            "health_test", "health_test.const", "homeassistant", "homeassistant.exceptions",
            "homeassistant.helpers", "homeassistant.helpers.issue_registry")}
        modules["health_test.const"].DOMAIN = "philips_homeid_plus"
        modules["homeassistant.exceptions"].HomeAssistantError = lambda **kwargs: kwargs
        modules["homeassistant.helpers"].issue_registry = SimpleNamespace(
            async_create_issue=Mock(), async_delete_issue=Mock(), IssueSeverity=SimpleNamespace(ERROR="error"))
        self.imports = patch.dict(sys.modules, modules)
        self.imports.start()
        self.addCleanup(self.imports.stop)
        self.transport = load("transport")
        self.errors = load("action_errors")
        self.repairs = load("repair_helpers")

    def test_transport_lifecycle_and_recovery(self):
        callbacks, cleanup = [], []
        unsubscribe = Mock()
        def add_listener(callback):
            callbacks.append(callback)
            return unsubscribe
        coordinator = SimpleNamespace(last_update_success=True, async_add_listener=add_listener)
        hass = SimpleNamespace(data={"philips_homeid_plus": {"one": {"coordinator": coordinator}}})
        entry = SimpleNamespace(entry_id="one", data={"is_tuya_pet": True}, async_on_unload=cleanup.append)
        self.transport.track_transport(hass, entry)
        good = self.transport.transport_diagnostics(hass, entry)
        self.assertTrue(good["available"])
        self.assertIsNotNone(good["last_successful_update"])
        coordinator.last_update_success = False
        callbacks[0]()
        bad = self.transport.transport_diagnostics(hass, entry)
        self.assertFalse(bad["available"])
        self.assertEqual(bad["last_successful_update"], good["last_successful_update"])
        coordinator.last_update_success = True
        callbacks[0]()
        self.assertIsNone(self.transport.transport_diagnostics(hass, entry)["reason"])
        for callback in cleanup:
            callback()
        unsubscribe.assert_called_once()
        self.assertEqual(self.transport.transport_diagnostics(hass, entry)["reason"], "entry_not_loaded")

    def test_cached_coap_state_is_not_a_successful_live_update(self):
        cleanup = []
        hass = SimpleNamespace(data={"philips_homeid_plus": {"one": SimpleNamespace(
            coordinator=SimpleNamespace(last_update_success=None, status={"pm25": 4}))}})
        entry = SimpleNamespace(entry_id="one", data={"is_airpurifier_coap": True}, async_on_unload=cleanup.append)
        self.transport.track_transport(hass, entry)
        self.assertIsNone(self.transport.transport_diagnostics(hass, entry)["last_successful_update"])

    def test_errors_are_classified_without_exporting_vendor_text(self):
        for error, key in ((TimeoutError(), "device_offline"),
                           (RuntimeError("PERMISSION_DENIED secret"), "permission_denied"),
                           (RuntimeError("INVALID_TOKEN secret"), "auth_expired"),
                           (RuntimeError("NOT_SUPPORTED"), "command_unsupported"),
                           (RuntimeError("FOOD_LEVEL_LOW"), "feeding_problem"),
                           (RuntimeError("private response"), "command_failed")):
            self.assertEqual(self.errors.error_key(error), key)
            self.assertEqual(self.errors.action_error(error)["translation_key"], key)
            self.assertNotIn("secret", str(self.errors.action_error(error)))

    def test_conflicts_require_active_matching_identity(self):
        entry = SimpleNamespace(data={"host": "192.0.2.1"}, options={})
        other = SimpleNamespace(domain="philips_airpurifier_coap", data={"host": "192.0.2.1"},
                                options={}, disabled_by=None, state="loaded")
        self.assertTrue(self.repairs.has_active_conflict(entry, [other]))
        other.disabled_by = "user"
        self.assertFalse(self.repairs.has_active_conflict(entry, [other]))
        other.disabled_by = None
        other.state = "not_loaded"
        self.assertFalse(self.repairs.has_active_conflict(entry, [other]))
        other.state = "loaded"
        other.data = {"host": "192.0.2.2"}
        self.assertFalse(self.repairs.has_active_conflict(entry, [other]))
