"""Account sensor identity and safe inventory projection."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class CoordinatorEntityStub:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class SensorStub:
    pass


class AccountSensorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = ("homeassistant", "homeassistant.components", "homeassistant.components.sensor",
                 "homeassistant.const", "homeassistant.helpers",
                 "homeassistant.helpers.update_coordinator", "sensor_test", "sensor_test.const")
        modules = {name: ModuleType(name) for name in names}
        modules["homeassistant.components.sensor"].SensorEntity = SensorStub
        modules["homeassistant.const"].EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
        modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntityStub
        modules["sensor_test.const"].DOMAIN = "philips_homeid_plus"
        path = (Path(__file__).resolve().parents[1] / "custom_components"
                / "philips_homeid_plus" / "account_sensor.py")
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("sensor_test.account_sensor", path)
            self.sensors = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.sensors)
        self.entry = SimpleNamespace(entry_id="hub", unique_id="homeid_account_example",
                                     title="Example account")
        self.coordinator = SimpleNamespace(data={"discovered_devices": 4, "configured_devices": 2})

    async def test_account_creates_only_two_diagnostic_count_sensors(self):
        hass = SimpleNamespace(data={"philips_homeid_plus": {
            "hub": {"account_coordinator": self.coordinator},
        }})
        add = Mock()
        await self.sensors.async_setup_entry(hass, self.entry, add)
        entities = add.call_args.args[0]
        self.assertEqual([entity.native_value for entity in entities], [4, 2])
        self.assertEqual(len({entity._attr_unique_id for entity in entities}), 2)
        self.assertTrue(all(entity._attr_entity_category == "diagnostic" for entity in entities))

    def test_sensor_identity_survives_rename_and_value_tracks_new_inventory(self):
        sensor = self.sensors.HomeIDAccountSensor(self.coordinator, self.entry, "discovered_devices")
        original_id = sensor._attr_unique_id
        self.entry.title = "Renamed account"
        renamed = self.sensors.HomeIDAccountSensor(self.coordinator, self.entry, "discovered_devices")
        self.assertEqual(renamed._attr_unique_id, original_id)
        self.coordinator.data = {"discovered_devices": 8}
        self.assertEqual(sensor.native_value, 8)
