"""Production payload and ownership contracts against the pinned, real SDK."""
from __future__ import annotations

from importlib.metadata import distribution
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
LIB = Path(distribution("petsseries").locate_file("petsseries"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Import real SDK modules without unrelated package __init__ side effects.
# Restore every public module substitution before the rest of the suite runs.
with patch.dict(sys.modules):
    package = ModuleType("petsseries")
    package.__path__ = [str(LIB)]
    sys.modules["petsseries"] = package
    load("petsseries.config", LIB / "config.py")
    models = load("petsseries.models", LIB / "models.py")
    for name in ["devices", "events", "meals"]:
        load(f"petsseries.{name}", LIB / f"{name}.py")
    adapter = load(
        "production_adapter_contract_test",
        ROOT / "custom_components/philips_homeid_plus/pet_series/production_adapter.py",
    )


def immediate(coroutine):
    """These mocked awaits finish immediately; any pending operation is an error."""
    try:
        pending = coroutine.send(None)
        raise AssertionError(f"Unexpected pending operation {pending!r}")
    except StopIteration as complete:
        return complete.value
    finally:
        coroutine.close()


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data, self.status, self.headers = data or {}, status, headers or {}
        self.request_info = SimpleNamespace(real_url="https://api.invalid")
        self.history = ()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=SimpleNamespace(real_url="https://api.invalid"),
                history=(), status=self.status, message="HTTP error",
            )

    async def json(self):
        return self.data

    async def text(self):
        return json.dumps(self.data)


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


class Client:
    def __init__(self, response=None):
        self.config = SimpleNamespace(base_url="https://verified-production.invalid")
        self.headers = {}
        self.session = Session(response or Response())
        self.aliases = {"cpp-a": "tuya-a", "cpp-b": "tuya-b"}

    def canonical_device_id(self, value):
        return self.aliases.get(value, value)

    def backend_device_id(self, value):
        return {canonical: backend for backend, canonical in self.aliases.items()}.get(value, value)

    async def ensure_token_valid(self):
        return None

    async def get_client(self):
        return self.session


HOME = models.Home(id="home-a", name="Home A")


def raw_meal(device="cpp-a", **extra):
    return {"id": "meal-a", "name": "Breakfast", "amount": 3, "time": "08:00", "repeatDays": [1, 2, 3], "deviceId": device, "enabled": True, "url": "meal-url", **extra}


def meal(device="tuya-a"):
    return models.Meal(id="meal-a", name="Breakfast", portion_amount=3, feed_time="08:00", repeat_days=[1, 2], device_id=device, enabled=True, url="meal-url")


def raw_event(**extra):
    return {"id": "event-a", "type": "meal_dispensed", "time": "2026-10-30T06:00:12Z", "source": "schedule", "deviceId": "cpp-a", "deviceVendorId": "tuya-a", "mealAmount": 3, **extra}


class ProductionAdapterTests(unittest.TestCase):
    def test_clean_sdk_version_is_the_declared_dependency(self):
        manifest = json.loads((ROOT / "custom_components/philips_homeid_plus/manifest.json").read_text())
        self.assertIn(f"petsseries=={distribution('petsseries').version}", manifest["requirements"])

    def test_each_manager_uses_verified_client_config(self):
        client = Client()
        for cls in [adapter.HomeIDMealsManager, adapter.HomeIDEventsManager, adapter.HomeIDDevicesManager]:
            self.assertIs(cls(client).config, client.config)

    def test_meals_from_two_devices_remain_separate(self):
        client = Client(Response({"item": [raw_meal("cpp-a"), raw_meal("cpp-b", id="meal-b")] }))
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual([entry.device_id for entry in result], ["tuya-a", "tuya-b"])
        self.assertEqual([entry.feed_time for entry in result], ["08:00", "08:00"])
        self.assertEqual([entry.portion_amount for entry in result], [3, 3])
        self.assertEqual(len([entry for entry in result if entry.device_id == "tuya-a"]), 1)

    def test_unknown_meal_owner_is_not_current_feeder(self):
        client = Client(Response({"item": [raw_meal("cpp-unknown")] }))
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual(result[0].device_id, "cpp-unknown")
        self.assertNotEqual(result[0].device_id, "tuya-a")

    def test_current_read_schema_allows_no_url_and_retains_disabled_schedule(self):
        data = raw_meal(enabled=False)
        del data["url"]
        client = Client(Response({"item": [data]}))
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual(result[0].url, "")
        self.assertFalse(result[0].enabled)
        self.assertEqual(result[0].feed_time, "08:00")
        self.assertEqual(client.session.calls[0][0], "GET")
        self.assertTrue(client.session.calls[0][1].endswith("/homes/home-a/meals"))
        self.assertNotIn("json", client.session.calls[0][2])

    def test_legacy_read_schema_and_explicit_zero_are_preserved(self):
        data = raw_meal(portionAmount=0, feedTime="09:10Z", amount=8, time="10:00")
        client = Client(Response({"item": [data]}))
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual(result[0].portion_amount, 0)
        self.assertEqual(result[0].feed_time, "09:10Z")

    def test_null_legacy_fields_fall_back_to_current_fields(self):
        client = Client(Response({"item": [raw_meal(portionAmount=None, feedTime=None)]}))
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual(result[0].portion_amount, 3)
        self.assertEqual(result[0].feed_time, "08:00")

    def test_read_failure_is_not_silently_an_empty_schedule(self):
        client = Client(Response(status=403))
        with self.assertRaises(aiohttp.ClientResponseError):
            immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        self.assertEqual(len(client.session.calls), 1)

    def test_event_vendor_identity_and_timestamp_preserved(self):
        original = raw_event()
        result = adapter.HomeIDEventsManager(Client()).parse_event(original)
        self.assertEqual(result.device_id, "tuya-a")
        self.assertEqual(result.device_external_id, "tuya-a")
        self.assertEqual(result.time, original["time"])
        self.assertEqual(result.meal_amount, 3)
        self.assertEqual(original["deviceId"], "cpp-a")
        self.assertNotIn("deviceExternalId", original)

    def test_event_cpp_identity_without_vendor_is_mapped(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceVendorId=None))
        self.assertEqual(result.device_id, "tuya-a")

    def test_client_can_preserve_existing_cpp_registry_identity(self):
        client = Client(Response({"item": [raw_meal()]}))
        client.aliases = {"tuya-a": "cpp-a", "cpp-a": "cpp-a"}
        result = immediate(adapter.HomeIDMealsManager(client).get_meals(HOME))
        event = adapter.HomeIDEventsManager(client).parse_event(raw_event())
        self.assertEqual(result[0].device_id, "cpp-a")
        self.assertEqual(event.device_id, "cpp-a")

    def test_other_feeder_vendor_wins_over_conflicting_cpp(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceVendorId="tuya-b"))
        self.assertEqual(result.device_id, "tuya-b")
        self.assertNotEqual(result.device_id, "tuya-a")

    def test_unknown_vendor_does_not_fall_back_to_known_cpp(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceVendorId="tuya-unknown"))
        self.assertEqual(result.device_id, "tuya-unknown")
        self.assertNotEqual(result.device_id, "tuya-a")

    def test_unknown_cpp_is_preserved(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceVendorId="", deviceId="cpp-unknown"))
        self.assertEqual(result.device_id, "cpp-unknown")

    def test_missing_identity_cannot_match_either_feeder(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceVendorId=None, deviceId=None))
        self.assertEqual(result.device_id, "")
        for target in ["tuya-a", "tuya-b"]:
            self.assertFalse(result.device_id is None or result.device_id == target)

    def test_existing_external_id_not_overwritten(self):
        result = adapter.HomeIDEventsManager(Client()).parse_event(raw_event(deviceExternalId="external-existing"))
        self.assertEqual(result.device_external_id, "external-existing")

    def test_create_meal_translates_copy_and_canonicalizes_response(self):
        client = Client(Response(status=201, headers={"Location": "/api/homes/home-a/meals/new-meal"}))
        original = meal()
        result = immediate(adapter.HomeIDMealsManager(client).create_meal(HOME, original))
        method, url, data = client.session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(data["json"]["deviceId"], "cpp-a")
        self.assertEqual(original.device_id, "tuya-a")
        self.assertEqual(result.device_id, "tuya-a")
        self.assertEqual(result.id, "new-meal")

    def test_update_meal_copy_remains_canonical_on_204(self):
        client = Client(Response(status=204))
        original = meal()
        result = immediate(adapter.HomeIDMealsManager(client).update_meal(HOME, original))
        self.assertEqual(result.device_id, "tuya-a")
        self.assertEqual(original.device_id, "tuya-a")
        self.assertEqual(client.session.calls[0][0], "PATCH")

    def test_create_200_current_response_and_exact_existing_payload(self):
        data = raw_meal()
        del data["url"]
        original = meal()
        client = Client(Response(data))
        result = immediate(adapter.HomeIDMealsManager(client).create_meal(HOME, original))
        self.assertEqual(result.device_id, "tuya-a")
        self.assertEqual(result.portion_amount, 3)
        self.assertEqual(result.url, "")
        self.assertEqual(original.device_id, "tuya-a")
        self.assertEqual(client.session.calls[0][2]["json"], {
            "deviceId": "cpp-a", "feedTime": "08:00", "name": "Breakfast",
            "portionAmount": 3, "repeatDays": [1, 2],
        })
        self.assertEqual(len(client.session.calls), 1)

    def test_update_200_current_response_and_exact_existing_payload(self):
        data = raw_meal(repeatDays=["1", "bad", 2], enabled=False)
        del data["url"]
        original = meal()
        client = Client(Response(data))
        result = immediate(adapter.HomeIDMealsManager(client).update_meal(HOME, original))
        self.assertEqual(result.device_id, "tuya-a")
        self.assertEqual(result.repeat_days, [1, 2])
        self.assertFalse(result.enabled)
        self.assertEqual(result.url, "")
        self.assertEqual(original.device_id, "tuya-a")
        self.assertEqual(client.session.calls[0][2]["json"], {
            "name": "Breakfast", "portionAmount": 3,
            "feedTime": "08:00", "repeatDays": [1, 2],
        })
        self.assertEqual(len(client.session.calls), 1)

    def test_both_write_200_legacy_responses_remain_compatible(self):
        for operation in ["create_meal", "update_meal"]:
            with self.subTest(operation=operation):
                data = raw_meal(portionAmount=4, feedTime="09:20Z")
                del data["amount"]
                del data["time"]
                client = Client(Response(data))
                manager = adapter.HomeIDMealsManager(client)
                result = immediate(getattr(manager, operation)(HOME, meal()))
                self.assertEqual(result.device_id, "tuya-a")
                self.assertEqual(result.feed_time, "09:20Z")
                self.assertEqual(result.portion_amount, 4)

    def test_missing_create_location_raises_without_retry(self):
        client = Client(Response(status=201))
        with self.assertRaises(aiohttp.ClientResponseError):
            immediate(adapter.HomeIDMealsManager(client).create_meal(HOME, meal()))
        self.assertEqual(len(client.session.calls), 1)

    def test_empty_update_id_is_rejected_before_http(self):
        client = Client()
        original = meal()
        original.id = ""
        with self.assertRaises(ValueError):
            immediate(adapter.HomeIDMealsManager(client).update_meal(HOME, original))
        self.assertEqual(client.session.calls, [])

    def test_failed_write_is_not_retried(self):
        for operation in ["create_meal", "update_meal"]:
            with self.subTest(operation=operation):
                client = Client(Response(status=500))
                manager = adapter.HomeIDMealsManager(client)
                with self.assertRaises(aiohttp.ClientResponseError):
                    immediate(getattr(manager, operation)(HOME, meal()))
                self.assertEqual(len(client.session.calls), 1)

    def test_settings_and_device_control_paths_translate_copies(self):
        device = models.Device(id="tuya-a", name="Feeder")
        client = Client()
        manager = adapter.HomeIDDevicesManager(client)
        immediate(manager.get_device_settings(HOME, device))
        self.assertTrue(client.session.calls[-1][1].endswith("/devices/cpp-a/settings"))
        client.session.response = Response(status=204)
        self.assertTrue(immediate(manager.update_device_settings(HOME, device, feeder_voice_audio_id="voice-test")))
        self.assertTrue(client.session.calls[-1][1].endswith("/devices/cpp-a/settings"))
        self.assertTrue(immediate(manager.rename_device(HOME, device, "New name")))
        self.assertTrue(client.session.calls[-1][1].endswith("/devices/cpp-a"))
        self.assertTrue(immediate(manager.delete_device(HOME, device)))
        self.assertTrue(client.session.calls[-1][1].endswith("/devices/cpp-a"))
        self.assertEqual(device.id, "tuya-a")

    def test_unknown_device_control_target_not_reassigned(self):
        client = Client()
        device = models.Device(id="unknown-device", name="Other device")
        immediate(adapter.HomeIDDevicesManager(client).get_device_settings(HOME, device))
        self.assertTrue(client.session.calls[0][1].endswith("/devices/unknown-device/settings"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
