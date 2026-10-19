"""Hardware filtering must not mistake a cloud outage for missing features."""
import importlib.util
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pet_capabilities", ROOT / "custom_components/philips_homeid_plus/pet_series/capabilities.py"
)
capabilities = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capabilities)


class PetCapabilitiesTests(unittest.TestCase):
    def test_camera_less_model_and_regional_suffix(self):
        for model in ("PAW3320", "PAW3320/02", " paw3320/02 "):
            device = SimpleNamespace(product_ctn=model)
            self.assertFalse(capabilities.supports_camera(device))
            for dp in capabilities.CAMERA_DATAPOINTS:
                self.assertFalse(capabilities.supports_datapoint(device, dp))

    def test_feeding_and_volume_not_inferred_from_missing_status(self):
        device = SimpleNamespace(product_ctn="PAW3320")
        for dp in ("201", "202", "205", "206", "231", "255"):
            self.assertTrue(capabilities.supports_datapoint(device, dp))

    def test_camera_and_unknown_models_keep_existing_behavior(self):
        for model in ("PAW5320/02", "", None, "future-model"):
            device = SimpleNamespace(product_ctn=model)
            self.assertTrue(capabilities.supports_camera(device))
            self.assertTrue(capabilities.supports_datapoint(device, "103"))
        self.assertTrue(capabilities.supports_camera(SimpleNamespace()))


class PetPlatformFilteringTests(unittest.IsolatedAsyncioTestCase):
    async def platform_entities(self, platform, model):
        """Execute the actual setup function with fixture-only dependencies.

        This checks platform wiring without importing Home Assistant or making
        cloud requests; real HA construction is covered separately by smoke tests.
        """
        folder = ROOT / "custom_components/philips_homeid_plus/pet_series"
        tree = ast.parse((folder / f"{platform}.py").read_text(encoding="utf-8-sig"))
        setup = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "async_setup_entry")
        dp_namespace = {}
        exec(compile((folder / "datapoints.py").read_text(), "datapoints.py", "exec"), dp_namespace)
        device = SimpleNamespace(id="fixture-device", product_ctn=model)
        coordinator = SimpleNamespace(data={"settings": {device.id: {}}, "event_types": [], "homes": []})
        namespace = {
            "DOMAIN": "fixture", "iter_home_devices": lambda _: [(None, device)],
            "datapoints": dp_namespace["datapoints"],
            "supports_camera": capabilities.supports_camera,
            "supports_datapoint": capabilities.supports_datapoint,
            "firmware": SimpleNamespace(has_ota_module=lambda *args: False),
        }
        if platform == "sensor":
            registers = next(node for node in tree.body if isinstance(node, ast.Assign)
                             and any(isinstance(target, ast.Name) and target.id == "_READ_ONLY_TUYA_DPS"
                                     for target in node.targets))
            namespace["_READ_ONLY_TUYA_DPS"] = ast.literal_eval(registers.value)
        constructors = {node.id for node in ast.walk(setup) if isinstance(node, ast.Name)
                        and node.id.startswith("PhilipsPetsSeries")}
        for name in constructors:
            namespace[name] = lambda *args, _kind=name: SimpleNamespace(kind=_kind, args=args)
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), setup], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), f"{platform}.py", "exec"), namespace)
        hass = SimpleNamespace(data={"fixture": {"entry": {
            "coordinator": coordinator, "client": SimpleNamespace(tuya_client=True), "bridge": object(),
        }}})
        entities = []
        await namespace["async_setup_entry"](hass, SimpleNamespace(entry_id="entry"), entities.extend)
        return entities

    async def test_camera_platforms_skip_only_camera_less_model(self):
        for platform in ("camera", "image", "select"):
            self.assertEqual(await self.platform_entities(platform, "PAW3320/02"), [])
            self.assertTrue(await self.platform_entities(platform, "PAW5320/02"))

    async def test_camera_switches_are_filtered(self):
        self.assertEqual(await self.platform_entities("switch", "PAW3320/02"), [])
        self.assertEqual(len(await self.platform_entities("switch", "PAW5320/02")), 5)

    async def test_sensor_filter_preserves_feeding_entities(self):
        small = await self.platform_entities("sensor", "PAW3320/02")
        camera = await self.platform_entities("sensor", "PAW5320/02")
        self.assertEqual(len(camera) - len(small), 3)
        kinds = {entity.kind for entity in small}
        self.assertIn("PhilipsPetsSeriesRawDpSensor", kinds)
        self.assertIn("PhilipsPetsSeriesNextMealSensor", kinds)
        self.assertNotIn("PhilipsPetsSeriesCameraOrientationSensor", kinds)
        self.assertNotIn("PhilipsPetsSeriesMotionSnapshotSensor", kinds)
        self.assertNotIn("PhilipsPetsSeriesStreamUrlSensor", kinds)
