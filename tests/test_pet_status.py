"""Exercise the coordinator's actual cloud-status block with mocked requests."""
import ast
import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

FOLDER = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/pet_series"


def load_action(filename, method, namespace):
    """Load an actual action method without importing HA or device clients."""
    tree = ast.parse((FOLDER / filename).read_text(encoding="utf-8-sig"))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == method)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), filename, "exec"), namespace)
    return namespace[method]


class PetFeedCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_button_mapping_does_not_change_existing_number_register(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("feed_capabilities", FOLDER / "capabilities.py")
        capabilities = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(capabilities)
        for model, expected in (("PAW3320/02", "101"), ("PAW5320/02", "201")):
            device = SimpleNamespace(product_ctn=model, id="fixture", name="Fixture feeder")
            client = SimpleNamespace(auth=SimpleNamespace(id_token="fixture"), publish_cloud_dps=AsyncMock())
            coordinator = SimpleNamespace(tuya_device_id=lambda _: "fixture", async_request_refresh=AsyncMock())
            entity = SimpleNamespace(_device=device, _client=client, coordinator=coordinator,
                _dp_id="201", _scale=0, _attr_name="Fixture",
                _attr_native_min_value=0, _attr_native_max_value=20)
            namespace = {"command_datapoint": capabilities.command_datapoint,
                "_LOGGER": logging.getLogger(__name__), "HomeAssistantError": RuntimeError,
                "math": math, "ServiceValidationError": lambda **kwargs: ValueError("invalid"),
                "DOMAIN": "fixture", "action_error": lambda error: RuntimeError("failed")}
            press = load_action("button.py", "async_press", namespace)
            set_number = load_action("number.py", "async_set_native_value", namespace)
            await press(entity)
            client.publish_cloud_dps.assert_awaited_once_with("fixture", {expected: 1.0})
            client.publish_cloud_dps.reset_mock()
            await set_number(entity, 3)
            client.publish_cloud_dps.assert_awaited_once_with("fixture", {"201": 3})
            self.assertEqual(coordinator.async_request_refresh.await_count, 2)
            client.publish_cloud_dps.reset_mock()
            for invalid in (-1, 21, 1.5, float("nan"), float("inf"), True):
                with self.assertRaises(ValueError):
                    await set_number(entity, invalid)
            client.publish_cloud_dps.assert_not_awaited()


class PetStatusTests(unittest.IsolatedAsyncioTestCase):
    async def read_status(self, *, definition_error=False, status_error=False, fallback=None):
        tree = ast.parse((FOLDER / "__init__.py").read_text(encoding="utf-8-sig"))
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "device.id in settings")
        function = ast.AsyncFunctionDef(name="run", args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=[block], decorator_list=[])
        client = SimpleNamespace(
            get_cloud_device_definition=AsyncMock(side_effect=RuntimeError("fixture") if definition_error else None, return_value={"schema": "fixture"}),
            get_cloud_device_status=AsyncMock(side_effect=RuntimeError("fixture") if status_error else None, return_value={"dps": '{"101": 0, "231": 80}'}),
        )
        namespace = {
            "self": SimpleNamespace(_client=client, tuya_device_id=lambda _: "fixture"),
            "device": SimpleNamespace(id="fixture", product_ctn="PAW3320/02"),
            "settings": {"fixture": {}}, "device_definitions": {},
            "tuya_status": fallback, "json": json, "_LOGGER": logging.getLogger(__name__),
            "datapoints": {"231": {"dpCode": "device_volume"}},
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "status-fixture", "exec"), namespace)
        await namespace["run"]()
        return namespace, client

    async def test_definition_failure_does_not_block_status_or_aliases(self):
        data, client = await self.read_status(definition_error=True)
        client.get_cloud_device_status.assert_awaited_once_with("fixture")
        self.assertEqual(data["device_definitions"]["fixture"], {})
        status = data["settings"]["fixture"]["tuya_status"]
        self.assertEqual(status["device_volume"], 80)
        self.assertEqual(status["feed_num"], 0)

    async def test_status_failure_uses_existing_fallback(self):
        data, _ = await self.read_status(status_error=True, fallback={"231": 40})
        self.assertEqual(data["settings"]["fixture"]["tuya_status"], {"231": 40})

    async def test_both_failures_leave_mapping_not_none(self):
        data, _ = await self.read_status(definition_error=True, status_error=True)
        self.assertEqual(data["settings"]["fixture"]["tuya_status"], {})
