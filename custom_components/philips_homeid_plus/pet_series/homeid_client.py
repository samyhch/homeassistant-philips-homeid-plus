"""Pet Series capabilities authenticated exclusively through HomeID."""
from __future__ import annotations

from dataclasses import replace

from petsseries import PetsSeriesClient
from petsseries.config import Config
from petsseries.models import Device

from ..account_session import homeid_tokens
from ..cloud_api import CloudAuthError
from ..const import DOMAIN
from ..homeid_tuya import session_for
from .identity import stable_device_identity
from .production_adapter import HomeIDDevicesManager, HomeIDEventsManager, HomeIDMealsManager


def _registry_identities(hass, entry):
    """Read this entry's existing identities without modifying either registry."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    rows = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    unique_ids = tuple(row.unique_id for row in rows)
    devices = dr.async_get(hass)
    linked = {}
    for row in rows:
        device = devices.async_get(row.device_id) if row.device_id else None
        if device is None:
            continue
        identities = tuple(str(value) for domain, value in device.identifiers if domain == DOMAIN)
        for identity in identities:
            linked[identity] = identities
    return unique_ids, linked


class HomeIDPetsClient(PetsSeriesClient):
    """Keep the existing API managers; replace their authentication boundary."""

    def __init__(self, hass, entry):
        super().__init__(token_file=None)
        self.hass = hass
        self.entry = entry
        self.homeid_tuya = session_for(hass, entry)
        self._fallback_home_id = None
        self._tuya_only_devices: set[str] = set()
        self._unsupported_legacy_settings: set[tuple[str, str]] = set()
        # HomeID 8.22 uses production, while petsseries 1.1.0 defaults to prd.
        # An authenticated read-only comparison confirmed that prd silently
        # returns empty meal/history lists for these migrated HomeID devices.
        base_url = "https://petseries.production.nbx.iot.versuni.com"
        self.config = Config(base_url=base_url,
                             consumer_url=base_url + "/api/consumer",
                             homes_url=base_url + "/api/homes")
        self.meals = HomeIDMealsManager(self)
        self.events = HomeIDEventsManager(self)
        self.devices_manager = HomeIDDevicesManager(self)
        self.homes_manager.config = self.config
        self._canonical_ids: dict[str, str] = {}
        self._backend_ids: dict[str, str] = {}
        self._home_devices: dict[str, list] = {}
        self._home_errors: dict[str, Exception] = {}
        self._target_home_id: str | None = None
        self._allow_fallback = True
        self._registered_unique_ids, self._linked_ids = _registry_identities(hass, entry)

    async def initialize(self):
        await self.ensure_token_valid()

    async def ensure_token_valid(self):
        tokens = await homeid_tokens(self.hass, self.entry)
        self.auth.access_token = tokens["access_token"]
        self.auth.id_token = tokens["id_token"]
        self.headers = {
            "Authorization": "Bearer " + tokens["access_token"],
            "Accept": "application/json",
            "User-Agent": "HomeID/8.22.0",
        }

    async def _tuya_action(self, action, payload, *, version="1.0", country_code="359"):
        await self.ensure_token_valid()
        result = await self.homeid_tuya.call(action, payload, version=version)
        self._tuya_mobile = self.homeid_tuya.client
        return result

    def canonical_device_id(self, device_id):
        """Keep the established Tuya identity used by HA's entity registry."""
        if device_id is None:
            return ""
        value = str(device_id)
        return self._canonical_ids.get(value, value)

    def backend_device_id(self, device_id):
        """Translate back only when addressing the Versuni backend."""
        value = str(device_id)
        return self._backend_ids.get(value, value)

    async def get_homes(self):
        homes = await super().get_homes()
        # Resolve every home's device list before generating any fallback.
        # Otherwise the other feeder's first home would create a synthetic
        # duplicate before the real matching device in the second home.
        discovered = {}
        # Retain previously verified aliases if an unrelated shared home fails.
        canonical_ids = dict(self._canonical_ids)
        backend_ids = dict(self._backend_ids)
        errors = {}
        target_home = None
        target = self.entry.data.get("tuya_device_id")
        for home in homes:
            try:
                devices = await super().get_devices(home)
            except Exception as error:
                status = getattr(error, "status_code", None) or getattr(error, "status", None)
                if isinstance(error, CloudAuthError) or status == 401:
                    raise
                errors[home.id] = error
                continue
            discovered[home.id] = devices
            for device in devices:
                backend_id = str(device.id)
                vendor_id = str(device.vendor_id or device.id)
                canonical_id = stable_device_identity(
                    self._registered_unique_ids, backend_id, vendor_id,
                    self._linked_ids.get(vendor_id, ()),
                )
                canonical_ids[backend_id] = canonical_id
                canonical_ids[vendor_id] = canonical_id
                canonical_ids[canonical_id] = canonical_id
                backend_ids[canonical_id] = backend_id
                backend_ids[vendor_id] = backend_id
                backend_ids[backend_id] = backend_id
                if vendor_id == target or backend_id == target:
                    target_home = home.id
        if target and target_home is None and errors:
            # Keep the last good coordinator data if its device may be in the
            # inaccessible home. Never invent a replacement in another home.
            raise next(iter(errors.values()))
        self._home_devices = discovered
        self._canonical_ids = canonical_ids
        self._backend_ids = backend_ids
        self._home_errors = errors
        # Failed discovery is not evidence that the target has no real record.
        self._allow_fallback = not errors
        self._target_home_id = target_home
        # Each feeder entry owns its actual home. Returning every account home
        # to every entry also creates duplicate home-wide invite sensors.
        return [home for home in homes if home.id == target_home] if target_home else homes

    async def get_mode_devices(self, home):
        devices = await super().get_mode_devices(home)
        return [replace(device, id=self.canonical_device_id(device.id))
                for device in devices]

    async def update_device_settings(self, home, device_id, settings):
        return await super().update_device_settings(
            home, self.backend_device_id(device_id), settings)

    async def get_devices(self, home):
        if home.id in self._home_errors:
            raise self._home_errors[home.id]
        devices = self._home_devices.get(home.id)
        if devices is None:
            devices = await super().get_devices(home)
        target = self.entry.data.get("tuya_device_id")
        if target:
            devices = [d for d in devices
                       if (getattr(d, "vendor_id", None) or d.id) == target or str(d.id) == target]
        devices = [replace(device, id=self.canonical_device_id(device.id))
                   for device in devices]
        for device in devices:
            self._tuya_only_devices.discard(str(device.id))
            self._unsupported_legacy_settings.discard((str(device.id), "mode"))
            self._unsupported_legacy_settings.discard((str(device.id), "full"))
        # HomeID still exposes the account homes through the former Pet Series
        # API, but feeder discovery moved to HomeID/Tuya and /devices can now
        # legitimately be empty.  The config entry already contains the Tuya
        # device selected from HomeID, so create the same Device model that the
        # existing Pet Series platforms expect.  Assign it to one home only to
        # avoid duplicate entities when an account contains multiple homes.
        if (not devices and target and self._allow_fallback and self._target_home_id is None
                and self._fallback_home_id in (None, home.id)):
            self._fallback_home_id = home.id
            self._tuya_only_devices.add(str(target))
            devices = [Device(
                id=target,
                name=self.entry.title,
                product_ctn=self.entry.data.get("model") or "Philips Pet Series",
                product_id=self.entry.data.get("cpp_id"),
                vendor_id=target,
                external_id=target,
            )]
        for device in devices:
            # The installed platforms use the family code for capability tests.
            device.product_ctn = str(
                device.product_ctn or self.entry.data.get("model") or "Philips Pet Series"
            ).strip().upper().split("/")[0]
        return devices

    def has_legacy_settings(self, device_id: str, resource: str = "mode") -> bool:
        """Probe once; skip only a confirmed missing synthetic-device resource."""
        return (str(device_id), resource) not in self._unsupported_legacy_settings

    def note_legacy_settings_error(self, device_id: str, error: Exception,
                                   resource: str = "mode") -> bool:
        """Classify 400/404 only for Tuya-only records, never genuine CPP devices.

        Authentication, DNS, timeout and 5xx failures remain actual errors.
        A reload or a genuine discovery record resets this capability cache.
        """
        status = getattr(error, "status_code", None) or getattr(error, "status", None)
        if str(device_id) not in self._tuya_only_devices or status not in (400, 404):
            return False
        self._unsupported_legacy_settings.add((str(device_id), resource))
        return True

    async def close(self):
        # DiscoveryManager creates an independent owned session in petsseries
        # 1.1.0. The base client does not close that manager itself.
        try:
            await self.discovery_manager.close()
        finally:
            await super().close()
        # HomeID owns the saved refresh token and the cached Tuya session uses
        # HA's shared HTTP session; neither is revoked or closed here.
