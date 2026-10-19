"""Regression tests for entry-scoped Repair creation and removal."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class RepairTests(unittest.TestCase):
    def test_notice_has_stable_entry_identity_and_can_be_cleared(self):
        registry = SimpleNamespace(
            async_create_issue=Mock(), async_delete_issue=Mock(),
            IssueSeverity=SimpleNamespace(ERROR="error"),
        )
        modules = {}
        for name in ("homeassistant", "homeassistant.helpers", "repair_test",
                     "repair_test.const"):
            modules[name] = ModuleType(name)
        modules["homeassistant.helpers"].issue_registry = registry
        modules["repair_test.const"].DOMAIN = "philips_homeid_plus"
        path = (Path(__file__).resolve().parents[1] / "custom_components"
                / "philips_homeid_plus" / "repair_helpers.py")
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("repair_test.repair_helpers", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        hass = object()
        entry = SimpleNamespace(entry_id="feeder_entry", title="Example feeder")
        module.report_missing_pet_devices(hass, entry)
        args, kwargs = registry.async_create_issue.call_args
        self.assertEqual(args, (hass, "philips_homeid_plus", "missing_pet_devices_feeder_entry"))
        self.assertFalse(kwargs["is_fixable"])
        self.assertEqual(kwargs["translation_key"], "missing_pet_devices")
        module.clear_missing_pet_devices(hass, entry)
        registry.async_delete_issue.assert_called_once_with(*args)
