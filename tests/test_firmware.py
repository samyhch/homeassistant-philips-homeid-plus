"""Firmware offers must not use stale history or expose installation controls."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

FOLDER = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/pet_series"
spec = importlib.util.spec_from_file_location("firmware_test", FOLDER / "firmware.py")
firmware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


class FirmwareTests(unittest.TestCase):
    def test_only_explicit_offer_is_an_update(self):
        for value in (1, "1"):
            self.assertTrue(firmware.is_offer({"upgradeStatus": value}))
        for value in (None, 0, "0", 2, "invalid"):
            self.assertFalse(firmware.is_offer({"upgradeStatus": value}))

    def test_live_definition_provides_wifi_version(self):
        coordinator = SimpleNamespace(data={"device_definitions": {"fixture": {"verSw": "2.0"}}})
        device = SimpleNamespace(id="fixture")
        self.assertEqual(firmware.installed_version(coordinator, device, "wifi"), "2.0")
        self.assertIsNone(firmware.offered_version(coordinator, device, "wifi"))

    def test_install_feature_and_method_are_absent(self):
        tree = ast.parse((FOLDER / "update.py").read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        features = next(node for node in cls.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "_attr_supported_features" for target in node.targets))
        self.assertEqual(ast.unparse(features.value), "UpdateEntityFeature(0)")
        self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and node.name == "async_install" for node in cls.body))
