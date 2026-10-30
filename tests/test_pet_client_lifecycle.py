"""Exercise the actual client and reload handlers with registry/network fixtures."""
import ast
from dataclasses import dataclass, replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/pet_series"
spec = importlib.util.spec_from_file_location("pet_client_identity_test", ROOT / "identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


@dataclass
class Device:
    id: str
    name: str = "Fixture feeder"
    product_ctn: str | None = "PAW3320/02"
    product_id: str | None = None
    vendor_id: str | None = None
    external_id: str | None = None


class Manager:
    def __init__(self, client):
        self.config = client.config


class BaseClient:
    def __init__(self, **kwargs):
        self.config = SimpleNamespace()
        self.homes_manager = SimpleNamespace()
        self.discovery_manager = SimpleNamespace(close=AsyncMock())
        self.close_base = AsyncMock()
        self.homes = [SimpleNamespace(id="other-home"), SimpleNamespace(id="own-home")]
        self.devices = {"other-home": [Device("cpp-other", vendor_id="tuya-other")],
                        "own-home": [Device("cpp-own", vendor_id="tuya-own")]}

    async def get_homes(self):
        return self.homes

    async def get_devices(self, home):
        value = self.devices[home.id]
        if isinstance(value, Exception):
            raise value
        return value

    async def get_mode_devices(self, home):
        return self.devices[home.id]

    async def update_device_settings(self, *args):
        self.last_update = args
        return True

    async def close(self):
        await self.close_base()


class AuthError(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def load_client():
    tree = ast.parse((ROOT / "homeid_client.py").read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "HomeIDPetsClient")
    namespace = {
        "PetsSeriesClient": BaseClient, "replace": replace, "Device": Device,
        "Config": SimpleNamespace, "CloudAuthError": AuthError,
        "session_for": lambda *args: object(),
        "_registry_identities": lambda hass, entry: (hass.unique_ids, hass.linked_ids),
        "stable_device_identity": identity.stable_device_identity,
        "HomeIDMealsManager": Manager, "HomeIDEventsManager": Manager,
        "HomeIDDevicesManager": Manager,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "homeid_client.py"), "exec"), namespace)
    return namespace["HomeIDPetsClient"]


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = SimpleNamespace(unique_ids=(), linked_ids={})
        self.entry = SimpleNamespace(title="Fixture", data={"tuya_device_id": "tuya-own", "model": "PAW3320"})
        self.client = load_client()(self.hass, self.entry)

    async def test_one_discovered_home_without_synthetic_duplicate(self):
        homes = await self.client.get_homes()
        self.assertEqual([h.id for h in homes], ["own-home"])
        self.assertEqual(await self.client.get_devices(self.client.homes[0]), [])
        devices = await self.client.get_devices(homes[0])
        self.assertEqual([d.id for d in devices], ["tuya-own"])
        self.assertEqual(devices[0].product_ctn, "PAW3320")
        self.assertEqual(self.client.devices["own-home"][0].id, "cpp-own")

    async def test_existing_cpp_entities_keep_their_identity(self):
        self.client._registered_unique_ids = ("cpp-own_next_meal", "cpp-own_meal_calendar")
        homes = await self.client.get_homes()
        self.assertEqual((await self.client.get_devices(homes[0]))[0].id, "cpp-own")
        self.assertEqual(self.client.canonical_device_id("tuya-own"), "cpp-own")

    async def test_old_cpp_linked_through_registry_survives_backend_migration(self):
        self.client._registered_unique_ids = ("previous-cpp_meal_calendar",)
        self.client._linked_ids = {"tuya-own": ("previous-cpp", "tuya-own")}
        homes = await self.client.get_homes()
        self.assertEqual((await self.client.get_devices(homes[0]))[0].id, "previous-cpp")
        self.assertEqual(self.client.backend_device_id("previous-cpp"), "cpp-own")

    async def test_unknown_and_other_aliases_are_never_assigned_to_this_feeder(self):
        await self.client.get_homes()
        self.assertEqual(self.client.canonical_device_id("cpp-other"), "tuya-other")
        self.assertEqual(self.client.canonical_device_id("unrelated"), "unrelated")
        self.assertEqual(self.client.canonical_device_id(None), "")

    async def test_inaccessible_unrelated_home_does_not_break_own_home(self):
        self.client.devices["other-home"] = ApiError(403)
        homes = await self.client.get_homes()
        self.assertEqual([h.id for h in homes], ["own-home"])
        self.assertEqual((await self.client.get_devices(homes[0]))[0].id, "tuya-own")

    async def test_unknown_own_home_failure_keeps_verified_aliases_and_no_fallback(self):
        await self.client.get_homes()
        self.client.devices["own-home"] = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            await self.client.get_homes()
        self.assertEqual(self.client.backend_device_id("tuya-own"), "cpp-own")

    async def test_authentication_failures_are_not_cached_as_missing_home(self):
        for error in (AuthError("expired"), ApiError(401)):
            self.client.devices["other-home"] = error
            with self.assertRaises(type(error)):
                await self.client.get_homes()

    async def test_confirmed_absent_target_has_one_fallback(self):
        self.client.devices = {h.id: [] for h in self.client.homes}
        homes = await self.client.get_homes()
        devices = [device for home in homes for device in await self.client.get_devices(home)]
        self.assertEqual([d.id for d in devices], ["tuya-own"])

    async def test_mode_reads_and_writes_translate_without_mutating_source(self):
        await self.client.get_homes()
        home = self.client.homes[1]
        self.assertEqual((await self.client.get_mode_devices(home))[0].id, "tuya-own")
        self.assertEqual(self.client.devices[home.id][0].id, "cpp-own")
        await self.client.update_device_settings(home, "tuya-own", {"setting": 1})
        self.assertEqual(self.client.last_update, (home, "cpp-own", {"setting": 1}))

    async def test_only_confirmed_synthetic_resource_failures_are_cached(self):
        for status in (400, 404, 401, 403, 500):
            self.assertFalse(self.client.note_legacy_settings_error("genuine", ApiError(status)))
        self.client._tuya_only_devices.add("fixture")
        for status in (401, 403, 500):
            self.assertFalse(self.client.note_legacy_settings_error("fixture", ApiError(status)))
        self.assertTrue(self.client.note_legacy_settings_error("fixture", ApiError(404)))
        self.assertFalse(self.client.has_legacy_settings("fixture"))
        self.assertTrue(self.client.has_legacy_settings("fixture", "full"))

    async def test_owned_session_cleanup_survives_discovery_close_failure(self):
        self.client.discovery_manager.close.side_effect = RuntimeError("fixture")
        with self.assertRaises(RuntimeError):
            await self.client.close()
        self.client.close_base.assert_awaited_once()


class ReloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8-sig"))
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in ("_entry_reload_signature", "_async_update_listener")]
        self.namespace = {"HomeAssistant": object, "ConfigEntry": object, "DOMAIN": "fixture"}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "__init__.py"), "exec"), self.namespace)
        self.entry = SimpleNamespace(entry_id="entry", data={"model": "PAW5320", "cloud_refresh_token": "fixture"}, options={})
        self.runtime = {"reload_signature": self.namespace["_entry_reload_signature"](self.entry)}
        self.hass = SimpleNamespace(data={"fixture": {"entry": self.runtime}},
                                    config_entries=SimpleNamespace(async_reload=AsyncMock()))

    async def test_rotated_token_does_not_reload(self):
        self.entry.data = {**self.entry.data, "cloud_refresh_token": "rotated-fixture"}
        await self.namespace["_async_update_listener"](self.hass, self.entry)
        self.hass.config_entries.async_reload.assert_not_awaited()

    async def test_real_configuration_changes_reload_once(self):
        for field in ("model", "options"):
            self.setUp()
            if field == "options":
                self.entry.options = {"camera_mode": "always"}
            else:
                self.entry.data = {**self.entry.data, "model": "PAW3320"}
            await self.namespace["_async_update_listener"](self.hass, self.entry)
            await self.namespace["_async_update_listener"](self.hass, self.entry)
            self.hass.config_entries.async_reload.assert_awaited_once_with("entry")

    async def test_callback_after_unload_does_not_recreate_entry(self):
        self.hass.data["fixture"].pop("entry")
        await self.namespace["_async_update_listener"](self.hass, self.entry)
        self.hass.config_entries.async_reload.assert_not_awaited()


class StableIdentityTests(unittest.TestCase):
    def test_existing_entities_outweigh_only_the_old_legacy_button(self):
        existing = ("tuya_dispense_one_portion", "cpp_meal_calendar", "cpp_next_meal")
        self.assertEqual(identity.stable_device_identity(existing, "cpp", "tuya"), "cpp")

    def test_new_and_existing_tuya_entries_keep_tuya_identity(self):
        for existing in ((), ("tuya_next_meal",)):
            self.assertEqual(identity.stable_device_identity(existing, "cpp", "tuya"), "tuya")


if __name__ == "__main__":
    unittest.main()
