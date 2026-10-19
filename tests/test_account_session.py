"""Account refresh isolation, cache, concurrency and failure regressions."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class AccountSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = SimpleNamespace(
            refresh_tokens=AsyncMock(return_value={
                "access_token": "new-access", "refresh_token": "rotated", "expires_in": 300,
            }),
            close=AsyncMock(),
        )
        self.factory = Mock(return_value=self.api)
        cloud = ModuleType("account_test.cloud_api")
        cloud.PhilipsCloudAPI = self.factory
        constants = ModuleType("account_test.const")
        constants.CONF_CLOUD_REFRESH_TOKEN = "cloud_refresh_token"
        constants.CONF_OAUTH_CLIENT = "oauth_client"
        constants.DOMAIN = "philips_homeid_plus"
        constants.OAUTH_CLIENT_HOMEID = "homeid"
        modules = {
            "account_test": ModuleType("account_test"),
            "account_test.cloud_api": cloud,
            "account_test.const": constants,
        }
        self.imports = patch.dict(sys.modules, modules)
        self.imports.start()
        self.addCleanup(self.imports.stop)
        path = (Path(__file__).resolve().parents[1] / "custom_components"
                / "philips_homeid_plus" / "account_session.py")
        spec = importlib.util.spec_from_file_location("account_test.account_session", path)
        self.sessions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sessions)
        self.first = self.entry("first", "original")
        self.second = self.entry("second", "original")
        self.other = self.entry("another_account", "other-token")
        self.airplus = self.entry("airplus", "original", "airplus")
        self.entries = [self.first, self.second, self.other, self.airplus]

        def update(entry, *, data):
            entry.data = data

        self.registry = SimpleNamespace(
            async_entries=Mock(return_value=self.entries),
            async_update_entry=Mock(side_effect=update),
        )
        self.hass = SimpleNamespace(data={}, config_entries=self.registry)

    @staticmethod
    def entry(entry_id, token, client="homeid"):
        return SimpleNamespace(
            entry_id=entry_id, title=entry_id,
            data={"cloud_refresh_token": token, "oauth_client": client},
        )

    def test_saved_sessions_deduplicate_devices_and_exclude_airplus(self):
        empty = self.entry("empty", "")
        legacy = SimpleNamespace(entry_id="legacy", data={"cloud_refresh_token": "legacy-token"})
        result = self.sessions.saved_homeid_sessions([*self.entries, empty, legacy])
        self.assertEqual([entry.entry_id for entry in result], ["first", "another_account", "legacy"])

    async def test_concurrent_devices_refresh_once_and_share_rotated_token(self):
        async def refresh(*args):
            await asyncio.sleep(0)
            return {"access_token": "new-access", "refresh_token": "rotated", "expires_in": 300}

        self.api.refresh_tokens.side_effect = refresh
        first, second = await asyncio.gather(
            self.sessions.homeid_tokens(self.hass, self.first),
            self.sessions.homeid_tokens(self.hass, self.second),
        )
        self.assertEqual(first, second)
        self.api.refresh_tokens.assert_awaited_once_with("original", "homeid")
        self.assertEqual(self.first.data["cloud_refresh_token"], "rotated")
        self.assertEqual(self.second.data["cloud_refresh_token"], "rotated")
        self.assertEqual(self.other.data["cloud_refresh_token"], "other-token")
        self.assertEqual(self.airplus.data["cloud_refresh_token"], "original")
        self.api.close.assert_awaited_once()

    async def test_cache_returns_tokens_without_extra_network_request(self):
        await self.sessions.homeid_tokens(self.hass, self.first)
        await self.sessions.homeid_tokens(self.hass, self.first)
        self.assertEqual(self.factory.call_count, 1)
        self.api.close.assert_awaited_once()

    async def test_refresh_response_can_omit_replacement_token(self):
        self.api.refresh_tokens.return_value = {"access_token": "new-access", "expires_in": 300}
        result = await self.sessions.homeid_tokens(self.hass, self.first)
        self.assertEqual(result["refresh_token"], "original")
        self.assertEqual(self.second.data["cloud_refresh_token"], "original")

    async def test_failed_refresh_closes_client_and_leaves_credentials_unchanged(self):
        self.api.refresh_tokens.side_effect = RuntimeError("example service failure")
        with self.assertRaisesRegex(RuntimeError, "example service failure"):
            await self.sessions.homeid_tokens(self.hass, self.first)
        self.api.close.assert_awaited_once()
        self.registry.async_update_entry.assert_not_called()
        self.assertEqual(self.first.data["cloud_refresh_token"], "original")

    async def test_airplus_session_cannot_use_homeid_refresh(self):
        with self.assertRaises(ValueError):
            await self.sessions.homeid_tokens(self.hass, self.airplus)
        self.factory.assert_not_called()

    async def test_missing_token_fails_before_creating_client(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            await self.sessions.homeid_tokens(self.hass, self.entry("empty", ""))
        self.factory.assert_not_called()

    async def test_expired_cache_is_refreshed(self):
        with patch.object(self.sessions.time, "monotonic", return_value=100):
            await self.sessions.homeid_tokens(self.hass, self.first)
        with patch.object(self.sessions.time, "monotonic", return_value=400):
            await self.sessions.homeid_tokens(self.hass, self.first)
        self.assertEqual(self.api.refresh_tokens.await_count, 2)

    async def test_invalid_expiry_does_not_cache_a_token_forever(self):
        self.api.refresh_tokens.return_value["expires_in"] = None
        await self.sessions.homeid_tokens(self.hass, self.first)
        await self.sessions.homeid_tokens(self.hass, self.first)
        self.assertEqual(self.api.refresh_tokens.await_count, 2)

    def test_account_hub_is_preferred_over_device_entry_for_same_session(self):
        hub = self.entry("hub", "original")
        hub.data["is_homeid_account"] = True
        result = self.sessions.saved_homeid_sessions([*self.entries, hub])
        self.assertEqual(result[0].entry_id, "hub")
        self.assertEqual(len(result), 2)

    def test_reauthentication_updates_only_the_shared_homeid_session(self):
        self.sessions.save_reauthenticated_session(self.hass, self.first, {
            "refresh_token": "reauthenticated", "access_token": "new-access",
        })
        self.assertEqual(self.first.data["cloud_refresh_token"], "reauthenticated")
        self.assertEqual(self.second.data["cloud_refresh_token"], "reauthenticated")
        self.assertEqual(self.other.data["cloud_refresh_token"], "other-token")
        self.assertEqual(self.airplus.data["cloud_refresh_token"], "original")

    async def test_rotation_is_persisted_before_client_cleanup_can_cancel(self):
        self.api.close.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.sessions.homeid_tokens(self.hass, self.first)
        self.assertEqual(self.first.data["cloud_refresh_token"], "rotated")
        self.assertEqual(self.second.data["cloud_refresh_token"], "rotated")
