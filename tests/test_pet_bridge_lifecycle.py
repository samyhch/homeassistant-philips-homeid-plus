"""Camera bridges must not collide, retry forever or outlive an entry reload.

Only fixture processes and coroutine tasks are used; these tests never open a
camera session, bind a socket, download a binary or call a cloud API.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


FOLDER = (
    Path(__file__).resolve().parents[1]
    / "custom_components/philips_homeid_plus/pet_series"
)
FIXTURE = "pet_bridge_lifecycle_fixture"


def _module(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules():
    """Import the actual modules while restoring every sys.modules stub."""
    modules = {
        FIXTURE: _module(FIXTURE, __path__=[]),
        "aiohttp": _module("aiohttp", web=SimpleNamespace()),
        "homeassistant": _module("homeassistant", __path__=[]),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.helpers": _module("homeassistant.helpers", __path__=[]),
        "homeassistant.helpers.aiohttp_client": _module(
            "homeassistant.helpers.aiohttp_client", async_get_clientsession=Mock()
        ),
        "homeassistant.helpers.network": _module(
            "homeassistant.helpers.network", get_url=Mock()
        ),
        "tuya_mobile": _module(
            "tuya_mobile", mqtt_client_id=Mock(), mqtt_credentials=Mock()
        ),
        f"{FIXTURE}.const": _module(
            f"{FIXTURE}.const",
            CONF_CAMERA_MODE="camera_mode",
            CONF_IDLE_TIMEOUT="idle_timeout",
        ),
    }
    with patch.dict(sys.modules, modules):
        capabilities = _load(f"{FIXTURE}.capabilities", FOLDER / "capabilities.py")
        bridge = _load(f"{FIXTURE}.bridge", FOLDER / "bridge.py")
    return bridge, capabilities


class BridgeImportIsolationTests(unittest.TestCase):
    def test_loader_leaves_existing_modules_and_fixture_namespace_unchanged(self):
        before = {
            name: module
            for name, module in sys.modules.items()
            if name.startswith(("homeassistant", "aiohttp", "tuya_mobile", FIXTURE))
        }
        load_modules()
        after = {
            name: module
            for name, module in sys.modules.items()
            if name.startswith(("homeassistant", "aiohttp", "tuya_mobile", FIXTURE))
        }
        self.assertEqual(before, after)


class BridgeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge, self.capabilities = load_modules()

    def manager(self, hass=None, entry_id="first", mode="on_demand"):
        if hass is None:
            hass = SimpleNamespace(data={})
        hass.async_create_background_task = (
            lambda coroutine, *, name: asyncio.create_task(coroutine, name=name)
        )
        entry = SimpleNamespace(
            entry_id=entry_id, data={}, options={"camera_mode": mode}
        )
        return self.bridge.PhilipsCameraBridgeManager(hass, entry, Mock(), Mock())

    def camera(self, device_id="camera"):
        return SimpleNamespace(id=device_id, product_ctn="PAW5320/02")

    def test_reservations_are_distinct_across_entries_and_stable_on_reload(self):
        hass = SimpleNamespace(data={})
        first = self.manager(hass, entry_id="first")
        second = self.manager(hass, entry_id="second")
        first_port = first._reserve_port("same-device-id")
        self.assertNotEqual(first_port, second._reserve_port("same-device-id"))
        self.assertNotEqual(first_port, second._reserve_port("other-device"))
        self.assertEqual(
            first_port, self.manager(hass, entry_id="first")._reserve_port("same-device-id")
        )

    async def test_known_camera_less_model_cannot_use_either_start_path(self):
        manager = self.manager()
        manager._async_start_device = AsyncMock()
        device = SimpleNamespace(id="feeder", product_ctn="PAW3320/02")
        self.assertIsNone(await manager.async_get_stream_url(device))
        manager._async_start_device.assert_not_awaited()
        with self.assertRaisesRegex(ValueError, "does not support a camera"):
            await self.manager()._async_start_device(device, 18560)

    async def test_startup_without_supported_camera_opens_no_endpoint(self):
        manager = self.manager()
        manager.coordinator.data = {
            "devices": [SimpleNamespace(id="feeder", product_ctn="PAW3320/02")]
        }
        manager._async_start_credential_server = AsyncMock()
        await manager.async_start()
        manager._async_start_credential_server.assert_not_awaited()

    def test_v013_capability_filter_keeps_unknown_models_behavior(self):
        self.assertFalse(
            self.capabilities.supports_camera(SimpleNamespace(product_ctn="PAW3320/02"))
        )
        for model in ("PAW5320/02", "", "future-model"):
            self.assertTrue(
                self.capabilities.supports_camera(SimpleNamespace(product_ctn=model))
            )
        self.assertTrue(self.bridge.PhilipsCameraBridgeManager._is_camera(self.camera()))

    async def test_unknown_model_keeps_existing_on_demand_stream_path(self):
        manager = self.manager()
        manager._sidecar_port = 1234
        device = SimpleNamespace(id="future-camera", product_ctn="future-model")

        async def start(device, port):
            manager._processes[device.id] = SimpleNamespace(stream_url="fixture://stream")

        manager._async_start_device = AsyncMock(side_effect=start)
        self.assertEqual(await manager.async_get_stream_url(device), "fixture://stream")
        manager._async_start_device.assert_awaited_once()
        with self.assertRaisesRegex(RuntimeError, "credential endpoint is not running"):
            await self.manager()._async_start_device(device, 18560)

    def test_short_lived_children_share_budget_and_cooldown_expires(self):
        manager = self.manager()
        with patch.object(self.bridge, "time", SimpleNamespace(monotonic=lambda: 1000)):
            delays = [manager._record_failure("camera", lifetime=2) for _ in range(8)]
        self.assertEqual(delays, [5, 10, 20, 40, 80, 160, 300, 1800])
        self.assertEqual(manager._retry_after["camera"], 2800)
        with patch.object(self.bridge, "time", SimpleNamespace(monotonic=lambda: 2801)):
            self.assertEqual(manager._record_failure("camera", lifetime=2), 5)

    def test_stable_session_resets_old_failure_budget(self):
        manager = self.manager()
        manager._restart_failures["camera"] = 7
        self.assertEqual(manager._record_failure("camera", lifetime=301), 5)

    async def test_viewer_does_not_bypass_cooldown(self):
        manager = self.manager()
        manager._retry_after["camera"] = self.bridge.time.monotonic() + 1800
        manager._async_start_device = AsyncMock()
        manager._async_start_credential_server = AsyncMock()
        self.assertIsNone(await manager.async_get_stream_url(self.camera()))
        manager._async_start_device.assert_not_awaited()
        manager._async_start_credential_server.assert_not_awaited()

    async def test_viewer_waiting_for_lock_cannot_restart_after_shutdown(self):
        manager = self.manager()
        manager._async_start_device = AsyncMock()
        manager._async_start_credential_server = AsyncMock()
        await manager._start_lock.acquire()
        viewer = asyncio.create_task(manager.async_get_stream_url(self.camera()))
        await asyncio.sleep(0)
        manager._stopping = True
        manager._start_lock.release()
        self.assertIsNone(await asyncio.wait_for(viewer, timeout=1))
        manager._async_start_device.assert_not_awaited()
        manager._async_start_credential_server.assert_not_awaited()

    async def test_failed_always_camera_does_not_unload_feeder(self):
        manager = self.manager(mode="always")
        manager.coordinator.data = {"devices": [self.camera()]}
        manager._async_start_credential_server = AsyncMock()
        manager._async_start_device = AsyncMock(side_effect=RuntimeError("fixture exit 1"))
        manager._schedule_retry = Mock()
        with self.assertLogs(self.bridge._LOGGER, level="ERROR"):
            await manager.async_start()
        manager._schedule_retry.assert_called_once_with(self.camera(), 18560, 5)
        self.assertFalse(manager._stopping)

    async def test_stale_monitor_does_not_restart_replaced_process(self):
        manager = self.manager()
        manager._processes["camera"] = object()
        manager._async_wait_for_failure = AsyncMock(return_value="exit 1")
        manager._schedule_retry = Mock()
        await manager._async_monitor(self.camera(), SimpleNamespace(device_key="camera"))
        manager._schedule_retry.assert_not_called()

    async def test_monitor_persists_failure_budget_into_replacement(self):
        manager = self.manager()
        now = self.bridge.time.monotonic()
        old = SimpleNamespace(
            device_key="camera", port=18560, started_at=now, last_requested=now
        )
        manager._processes["camera"] = old
        manager._restart_failures["camera"] = 4
        manager._async_wait_for_failure = AsyncMock(return_value="exit 1")
        manager._async_stop_bridge_process = AsyncMock()
        manager._schedule_retry = Mock()
        with self.assertLogs(self.bridge._LOGGER, level="ERROR"):
            await manager._async_monitor(self.camera(), old)
        self.assertEqual(manager._schedule_retry.call_args.args[2], 80)
        self.assertNotIn("camera", manager._processes)

    async def test_retry_honors_new_deadline_and_preserves_viewer_timestamp(self):
        manager = self.manager()
        clock = [1000]
        manager._retry_after["camera"] = 1015
        delays = []

        async def sleep(delay):
            delays.append(delay)
            clock[0] += delay

        async def start(device, port):
            manager._processes[str(device.id)] = SimpleNamespace(last_requested=0)

        manager._async_start_device = AsyncMock(side_effect=start)
        with (
            patch.object(self.bridge, "time", SimpleNamespace(monotonic=lambda: clock[0])),
            patch.object(self.bridge.asyncio, "sleep", side_effect=sleep),
        ):
            await manager._async_retry_device(self.camera(), 18560, 5, 1000)
        self.assertEqual(delays, [5, 10])
        manager._async_start_device.assert_awaited_once()
        self.assertEqual(manager._processes["camera"].last_requested, 1000)

    async def test_idle_on_demand_session_is_not_retried(self):
        manager = self.manager()
        manager._async_start_device = AsyncMock()
        with patch.object(self.bridge.asyncio, "sleep", new=AsyncMock()):
            await manager._async_retry_device(self.camera(), 18560, 5, None)
        manager._async_start_device.assert_not_awaited()

    async def test_shutdown_cancels_and_joins_retry_tasks(self):
        manager = self.manager()
        task = asyncio.create_task(asyncio.sleep(3600))
        manager._retry_tasks.add(task)
        await manager.async_stop()
        self.assertTrue(task.cancelled())
        self.assertFalse(manager._retry_tasks)

    async def test_reaping_bridge_joins_monitor_and_log_tasks(self):
        manager = self.manager()
        log_task = asyncio.create_task(asyncio.sleep(3600))
        monitor_task = asyncio.create_task(asyncio.sleep(3600))
        manager._processes["camera"] = SimpleNamespace(
            process=SimpleNamespace(returncode=0),
            log_task=log_task,
            monitor_task=monitor_task,
        )
        await manager._async_stop_bridge("camera")
        self.assertTrue(log_task.cancelled())
        self.assertTrue(monitor_task.cancelled())

    async def test_failure_wait_joins_cancelled_process_waiter(self):
        manager = self.manager()
        waiting = asyncio.Event()
        cancelled = asyncio.Event()

        async def process_wait():
            waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        failed = asyncio.Event()
        waiter = asyncio.create_task(manager._async_wait_for_failure(SimpleNamespace(
            process=SimpleNamespace(wait=process_wait), failed=failed, failures=[1, 2, 3]
        )))
        await asyncio.wait_for(waiting.wait(), timeout=1)
        failed.set()
        self.assertIn("stream failures", await asyncio.wait_for(waiter, timeout=1))
        self.assertTrue(cancelled.is_set())

    async def test_cancelled_start_cleans_child_and_joins_log_task(self):
        manager = self.manager()
        manager._sidecar_port = 1234
        manager.hass.config = SimpleNamespace(path=Mock(return_value="fixture-workdir"))
        manager._ensure_binary = AsyncMock(return_value=Path("fixture-binary"))
        manager._async_read_logs = AsyncMock()
        manager._async_wait_until_ready = AsyncMock(side_effect=asyncio.CancelledError)
        process = SimpleNamespace(returncode=None, wait=AsyncMock(return_value=0))
        process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))
        process.kill = Mock()
        cleanup = AsyncMock(wraps=manager._async_stop_bridge_process)
        manager._async_stop_bridge_process = cleanup
        with (
            patch.object(self.bridge.asyncio, "to_thread", new=AsyncMock()),
            patch.object(
                self.bridge.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await manager._async_start_device(self.camera(), 18560)
        cleanup.assert_awaited_once()
        self.assertTrue(cleanup.call_args.args[0].log_task.done())
        self.assertEqual(manager._processes, {})
        process.terminate.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_shutdown_during_readiness_cleans_unregistered_child(self):
        manager = self.manager()
        manager._sidecar_port = 1234
        manager.hass.config = SimpleNamespace(path=Mock(return_value="fixture-workdir"))
        manager._ensure_binary = AsyncMock(return_value=Path("fixture-binary"))
        manager._async_read_logs = AsyncMock()

        async def stop_during_readiness(_bridge):
            manager._stopping = True

        manager._async_wait_until_ready = AsyncMock(side_effect=stop_during_readiness)
        process = SimpleNamespace(returncode=None, wait=AsyncMock(return_value=0))
        process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))
        process.kill = Mock()
        with (
            patch.object(self.bridge.asyncio, "to_thread", new=AsyncMock()),
            patch.object(
                self.bridge.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await manager._async_start_device(self.camera(), 18560)
        self.assertEqual(manager._processes, {})
        process.terminate.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_existing_endpoint_is_not_started_twice(self):
        manager = self.manager()
        manager._runner = object()
        await manager._async_start_credential_server()

    async def test_failed_endpoint_is_cleaned_up_and_can_be_retried(self):
        manager = self.manager()
        runner = SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
        site = SimpleNamespace(
            start=AsyncMock(side_effect=RuntimeError("fixture bind failure")),
            _server=SimpleNamespace(sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))]),
        )
        fake_web = SimpleNamespace(
            Application=Mock(return_value=SimpleNamespace(router=SimpleNamespace(add_get=Mock()))),
            AppRunner=Mock(return_value=runner),
            TCPSite=Mock(return_value=site),
        )
        with patch.object(self.bridge, "web", fake_web):
            with self.assertRaisesRegex(RuntimeError, "fixture bind failure"):
                await manager._async_start_credential_server()
            self.assertIsNone(manager._runner)
            self.assertIsNone(manager._sidecar_port)
            runner.cleanup.assert_awaited_once()
            site.start = AsyncMock()
            await manager._async_start_credential_server()
        self.assertIs(manager._runner, runner)
        self.assertEqual(manager._sidecar_port, 1234)

    async def test_cancelled_endpoint_setup_is_cleaned_up(self):
        manager = self.manager()
        runner = SimpleNamespace(
            setup=AsyncMock(side_effect=asyncio.CancelledError), cleanup=AsyncMock()
        )
        fake_web = SimpleNamespace(
            Application=Mock(return_value=SimpleNamespace(router=SimpleNamespace(add_get=Mock()))),
            AppRunner=Mock(return_value=runner),
        )
        with patch.object(self.bridge, "web", fake_web), self.assertRaises(asyncio.CancelledError):
            await manager._async_start_credential_server()
        runner.cleanup.assert_awaited_once()
        self.assertIsNone(manager._runner)

    async def test_camera_stream_guard_preserves_v013_platform_filter(self):
        # Execute the real stream_source method. Importing the whole camera
        # platform would otherwise require an unrelated HA entity hierarchy.
        import ast

        tree = ast.parse((FOLDER / "camera.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "PhilipsPetsSeriesCamera")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "stream_source")
        namespace = {"supports_camera": self.capabilities.supports_camera}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "camera.py", "exec"), namespace)
        camera = SimpleNamespace(
            _device=SimpleNamespace(product_ctn="PAW3320/02"),
            _bridge=SimpleNamespace(async_get_stream_url=AsyncMock()),
        )
        self.assertIsNone(await namespace["stream_source"](camera))
        camera._bridge.async_get_stream_url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
