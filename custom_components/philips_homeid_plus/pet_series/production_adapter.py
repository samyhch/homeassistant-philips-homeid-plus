"""Translate production Pet API ownership without changing HA entity identities.

The client supplies a verified API config and discovery-backed, bidirectional
device aliases. Unknown IDs must pass through unchanged, never to a default
feeder. Backend requests use copies so registry-facing models stay stable.
"""
from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse

import aiohttp

from petsseries.devices import DevicesManager
from petsseries.events import EventsManager
from petsseries.meals import MealsManager
from petsseries.models import Meal


class HomeIDMealsManager(MealsManager):
    """Read current meal fields and expose canonical device ownership."""

    def __init__(self, client):
        super().__init__(client)
        self.config = client.config

    def _parse_meal(self, item):
        """Accept the HomeID and legacy field names; URL is optional metadata."""
        return Meal(
            id=item["id"],
            name=item["name"],
            portion_amount=(item.get("portionAmount")
                            if item.get("portionAmount") is not None else item.get("amount")),
            feed_time=(item.get("feedTime")
                       if item.get("feedTime") is not None else item.get("time")),
            repeat_days=item["repeatDays"],
            device_id=self.client.canonical_device_id(item["deviceId"]),
            enabled=item["enabled"],
            url=item.get("url") or "",
        )

    def _canonical_meal(self, meal):
        return replace(meal, device_id=self.client.canonical_device_id(meal.device_id))

    def _backend_meal(self, meal):
        return replace(meal, device_id=self.client.backend_device_id(meal.device_id))

    async def get_meals(self, home):
        await self.client.ensure_token_valid()
        session = await self.client.get_client()
        url = f"{self.config.base_url}/api/homes/{home.id}/meals"
        async with session.get(url, headers=self.client.headers) as response:
            response.raise_for_status()
            payload = await response.json()
        return [self._parse_meal(item) for item in payload.get("item", [])]

    async def create_meal(self, home, meal):
        """Keep SDK request fields/statuses; accept either response schema."""
        await self.client.ensure_token_valid()
        backend = self._backend_meal(meal)
        repeat_days = backend.repeat_days if backend.repeat_days is not None else list(range(1, 8))
        feed_time = self._iso_time(backend.feed_time)
        payload = {
            "deviceId": backend.device_id,
            "feedTime": feed_time,
            "name": backend.name,
            "portionAmount": backend.portion_amount,
            "repeatDays": repeat_days,
        }
        session = await self.client.get_client()
        headers = {**self.client.headers, "Content-Type": "application/json; charset=UTF-8"}
        url = f"{self.config.base_url}/api/homes/{home.id}/meals"
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 201:
                location = response.headers.get("Location")
                if not location:
                    raise aiohttp.ClientResponseError(
                        status=response.status,
                        message="Location header missing in response.",
                        request_info=response.request_info,
                        history=response.history,
                    )
                return self._canonical_meal(replace(
                    backend, id=urlparse(location).path.split("/")[-1],
                    feed_time=feed_time, repeat_days=repeat_days, enabled=True, url=location,
                ))
            if response.status == 200:
                data = await response.json()
                return self._parse_meal({"repeatDays": repeat_days, "enabled": True, **data})
            response.raise_for_status()
        raise RuntimeError("Failed to create meal")

    async def update_meal(self, home, meal):
        """No new commands or retries: retain the SDK's existing PATCH payload."""
        await self.client.ensure_token_valid()
        if not meal.id:
            raise ValueError("Meal ID must be provided for updating a meal.")
        backend = self._backend_meal(meal)
        repeat_days = backend.repeat_days if backend.repeat_days else list(range(1, 8))
        feed_time = self._iso_time(backend.feed_time)
        payload = {
            "name": backend.name,
            "portionAmount": backend.portion_amount,
            "feedTime": feed_time,
            "repeatDays": repeat_days,
        }
        session = await self.client.get_client()
        headers = {**self.client.headers, "Content-Type": "application/json; charset=UTF-8"}
        url = f"{self.config.base_url}/api/homes/{home.id}/meals/{backend.id}"
        async with session.patch(url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                normalized_days = self._int_days(data.get("repeatDays"), repeat_days)
                return self._parse_meal({**data, "repeatDays": normalized_days,
                                         "enabled": data.get("enabled", True)})
            if response.status == 204:
                return self._canonical_meal(replace(
                    backend, feed_time=feed_time, repeat_days=repeat_days,
                ))
            response.raise_for_status()
        raise RuntimeError("Failed to update meal")

    @staticmethod
    def _iso_time(value):
        """Preserve the SDK's handling of string and datetime/time values."""
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    @staticmethod
    def _int_days(value, fallback):
        """Preserve the SDK's update-response normalization."""
        if not isinstance(value, list):
            return fallback
        result = []
        for day in value:
            try:
                result.append(int(day))
            except (ValueError, TypeError, OverflowError):
                continue
        return result or fallback

    # Enable/disable/delete identify a meal by meal.id, not by device identity.


class HomeIDEventsManager(EventsManager):
    """Normalize event ownership before the SDK creates a typed event."""

    def __init__(self, client):
        super().__init__(client)
        self.config = client.config

    def parse_event(self, event):
        normalized = dict(event)
        vendor_id = event.get("deviceVendorId")
        identity = vendor_id if vendor_id not in (None, "") else event.get("deviceId")
        # The vendor field is authoritative even when unknown to discovery.
        # Missing identity must not be None: historical entity filters treated
        # None as a home-wide event, falsely crediting every feeder.
        normalized["deviceId"] = (
            self.client.canonical_device_id(str(identity))
            if identity not in (None, "") else ""
        )
        if vendor_id not in (None, "") and normalized.get("deviceExternalId") in (None, ""):
            normalized["deviceExternalId"] = vendor_id
        return super().parse_event(normalized)


class HomeIDDevicesManager(DevicesManager):
    """Translate settings/control request targets using copied device models."""

    def __init__(self, client):
        super().__init__(client)
        self.config = client.config

    def _backend_device(self, device):
        return replace(device, id=self.client.backend_device_id(device.id))

    async def get_device_settings(self, home, device):
        return await super().get_device_settings(home, self._backend_device(device))

    async def update_device_settings(
        self, home, device, filter_application_time=None, feeder_voice_audio_id=None
    ):
        return await super().update_device_settings(
            home, self._backend_device(device),
            filter_application_time=filter_application_time,
            feeder_voice_audio_id=feeder_voice_audio_id,
        )

    async def rename_device(self, home, device, new_name):
        return await super().rename_device(home, self._backend_device(device), new_name)

    async def delete_device(self, home, device):
        return await super().delete_device(home, self._backend_device(device))
