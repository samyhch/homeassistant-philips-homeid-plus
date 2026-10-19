"""A reload must not leave an old CoAP observer or reconnect timer running."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

FOLDER = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/airpurifier"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, FOLDER / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoAPLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_observer_reconnect_and_timer(self):
        timer = load("coap_fixture.timer", "timer.py")
        modules = {name: ModuleType(name) for name in (
            "aioairctrl", "homeassistant", "homeassistant.core", "homeassistant.exceptions", "coap_fixture",
            "coap_fixture.airpurifier", "coap_fixture.action_errors")}
        modules["aioairctrl"].CoAPClient = object
        modules["homeassistant.core"].CALLBACK_TYPE = object
        modules["homeassistant.core"].HomeAssistant = object
        modules["homeassistant.core"].callback = lambda callback: callback
        modules["homeassistant.exceptions"].ConfigEntryNotReady = RuntimeError
        modules["coap_fixture.action_errors"].CoAPCommandClient = lambda client: client
        modules["coap_fixture.airpurifier.timer"] = timer
        with patch.dict(sys.modules, modules):
            module = load("coap_fixture.airpurifier.coordinator", "coordinator.py")
        client = SimpleNamespace(shutdown=AsyncMock())
        coordinator = module.Coordinator(None, client, "192.0.2.1", {})
        observer = asyncio.create_task(asyncio.Event().wait())
        reconnect = asyncio.create_task(asyncio.Event().wait())
        coordinator._task = observer
        coordinator._reconnect_task = reconnect
        await coordinator.shutdown()
        self.assertTrue(observer.cancelled())
        self.assertTrue(reconnect.cancelled())
        self.assertIsNone(coordinator._timer_disconnected._task)
        self.assertEqual(coordinator._listeners, [])
        client.shutdown.assert_awaited_once()

    async def test_timer_shutdown_while_callback_is_running(self):
        timer_module = load("timer_shutdown_fixture", "timer.py")
        entered = asyncio.Event()
        async def callback():
            entered.set()
            await asyncio.Event().wait()
        timer = timer_module.Timer(0, callback)
        timer.setAutoRestart(True)
        await asyncio.wait_for(entered.wait(), 1)
        await timer.async_shutdown()
        self.assertIsNone(timer._task)
        self.assertFalse(timer._auto_restart)
