"""Pet Series capabilities authenticated exclusively through HomeID."""
from __future__ import annotations

from petsseries import PetsSeriesClient
from petsseries.models import Device

from ..account_session import homeid_tokens
from ..homeid_tuya import session_for


class HomeIDPetsClient(PetsSeriesClient):
    """Keep the existing API managers; replace their authentication boundary."""

    def __init__(self, hass, entry):
        super().__init__(token_file=None)
        self.hass = hass
        self.entry = entry
        self.homeid_tuya = session_for(hass, entry)
        self._fallback_home_id = None

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

    async def get_devices(self, home):
        devices = await super().get_devices(home)
        target = self.entry.data.get("tuya_device_id")
        if target:
            devices = [d for d in devices if (getattr(d, "vendor_id", None) or d.id) == target]
        # HomeID still exposes the account homes through the former Pet Series
        # API, but feeder discovery moved to HomeID/Tuya and /devices can now
        # legitimately be empty.  The config entry already contains the Tuya
        # device selected from HomeID, so create the same Device model that the
        # existing Pet Series platforms expect.  Assign it to one home only to
        # avoid duplicate entities when an account contains multiple homes.
        if not devices and target and self._fallback_home_id in (None, home.id):
            self._fallback_home_id = home.id
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
            device.product_ctn = device.product_ctn.split("/")[0]
        return devices

    async def close(self):
        # HomeID owns refresh-token storage and HA owns the cached Tuya HTTP session.
        if self.session is not None:
            await self.session.close()
            self.session = None
