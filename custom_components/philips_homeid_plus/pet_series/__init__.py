from __future__ import annotations

import asyncio
import ipaddress
import json
import datetime as dt
import logging
import os
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.loader import async_get_integration
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

try:
    import petsseries
except ImportError as e:
    _LOGGER.error("Failed to import petsseries module: %s", e)
    raise

from petsseries.models import Event

from petsseries import PetsSeriesClient

from .const import (
    CONF_COUNTRY,
    CONF_HOME_IDS,
    CONF_ID_TOKEN,
    CONF_LANGUAGE,
    CONF_TIMEZONE,
    COUNTRY_DIAL_CODES,
    DOMAIN,
    REMOVED_DP_SENSORS,
)
from . import firmware, websocket
from .bridge import PhilipsCameraBridgeManager
from .frontend import JSModuleRegistration
from .lanbeacon import BeaconListener
from .datapoints import datapoints

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.IMAGE,
    Platform.CAMERA,
    Platform.UPDATE,
]

SCAN_INTERVAL = timedelta(minutes=5)

# Days of event history to request.  Enough that entities survive a local
# midnight rollover and a fault raised late in the evening stays visible.
EVENT_HISTORY_DAYS = 7


class PhilipsPetsSeriesDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data for Philips Pets Series sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: PetsSeriesClient,
        delay_between_calls: float = 1,
        home_ids: list[str] | None = None,
        tuya_device_id: str | None = None,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self._client = client
        self.delay_between_calls = delay_between_calls
        self.home_ids = set(home_ids or [])
        self._tuya_device_id = tuya_device_id
        self._ota_store = Store(hass, 1, f"{DOMAIN}.ota_history")
        self.ota_history: dict[str, list[dict]] = {}

    def tuya_device_id(self, device) -> str:
        """Return the Tuya devId associated with a Philips device."""
        return getattr(device, "vendor_id", None) or self._tuya_device_id or device.id

    async def _load_ota_history(self) -> None:
        """Load previously observed OTA metadata once per coordinator."""
        if self.ota_history:
            return
        stored = await self._ota_store.async_load()
        if isinstance(stored, dict):
            self.ota_history = stored

    async def _save_ota_records(self, device_id: str, records: list[dict]) -> None:
        """Persist OTA records so signed URLs are captured when offered."""
        if not records:
            return
        self.ota_history[device_id] = records
        await self._ota_store.async_save(self.ota_history)

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            await self._load_ota_history()
            try:
                homes = await self._client.get_homes()
            except RuntimeError as err:
                # A config-entry reload can leave the old aiohttp session
                # closed while the coordinator task is still winding down.
                if "Session is closed" not in str(err):
                    raise
                self._client.session = None
                homes = await self._client.get_homes()
            if self.home_ids:
                homes = [home for home in homes if str(home.id) in self.home_ids]
            devices = []
            home_devices_by_home = {}
            meals = []
            events_by_home_and_type = {}
            invites_by_home = {}
            settings = {}
            full_settings = {}
            firmware_info = {}
            product_firmware_info = {}
            device_definitions = {}
            event_types = Event.get_event_types()
            tuya_status = None
            use_local_tuya = False
            if self._client.tuya_client:
                try:
                    configured_ip = getattr(self._client.tuya_client.device, "address", None)
                    use_local_tuya = bool(configured_ip and ipaddress.ip_address(configured_ip).is_private)
                except (ValueError, AttributeError):
                    use_local_tuya = False
            if use_local_tuya:
                try:
                    # This is account/device-global; fetching it once avoids one
                    # blocking LAN request per device on every coordinator cycle.
                    tuya_status = await asyncio.to_thread(self._client.get_tuya_status)
                except Exception as err:
                    _LOGGER.warning("Failed to fetch Tuya status: %s", err)
            now = dt_util.now()
            # Look back several days rather than only at today: a midnight-only
            # window empties every event-derived entity at local midnight, which
            # made "last event" sensors go unknown and fault conditions clear
            # themselves on the date rollover instead of when actually resolved.
            from_date = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=EVENT_HISTORY_DAYS)
            to_date = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                days=1
            )

            for home in homes:
                try:
                    home_devices = await self._client.get_devices(home)
                    home_devices_by_home[home.id] = home_devices
                    devices.extend(home_devices)
                    _LOGGER.debug("Fetched %d devices for home %s", len(home_devices), home.id)
                except Exception as e:
                    _LOGGER.warning("Failed to fetch devices for home %s: %s", home.id, e)
                    continue

                await asyncio.sleep(self.delay_between_calls)

                # Fetch events
                for event_type in event_types:
                    try:
                        home_events = await self._client.events.get_events(
                            home,
                            from_date=from_date,
                            to_date=to_date,
                            types=str(event_type),
                        )
                        event_type_str = (
                            event_type
                            if isinstance(event_type, str)
                            else (
                                event_type.value
                                if hasattr(event_type, "value")
                                else str(event_type)
                            )
                        )

                        key = f"{home.id}_{event_type_str}"
                        events_by_home_and_type[key] = home_events
                    except Exception as e:
                        _LOGGER.warning("Failed to fetch events %s for home %s: %s", event_type, home.id, e)

                    await asyncio.sleep(self.delay_between_calls)

                # Fetch settings for devices
                for device in home_devices:
                    try:
                        device_settings = (
                            await self._client.get_settings(home, device.id)
                            if self._client.has_legacy_settings(device.id) else {}
                        )
                        settings[device.id] = device_settings or {}
                    except Exception as e:
                        if self._client.note_legacy_settings_error(device.id, e):
                            _LOGGER.debug("Tuya-only device has no legacy mode settings")
                        else:
                            _LOGGER.warning("Failed to fetch settings for device %s: %s", device.id, e)
                        settings[device.id] = {}

                    # Fetch full settings
                    try:
                        if self._client.has_legacy_settings(device.id, "full"):
                            device_full_settings = await self._client.devices_manager.get_device_settings(home, device)
                            full_settings[device.id] = device_full_settings
                    except Exception as e:
                        if self._client.note_legacy_settings_error(device.id, e, "full"):
                            _LOGGER.debug("Tuya-only device has no legacy full settings")
                        else:
                            _LOGGER.warning("Failed to fetch full settings for device %s: %s", device.id, e)

                    # Prefer the app-compatible cloud DP status. TinyTuya is
                    # only a fallback for installations with a real LAN IP.
                    if device.id in settings:
                        cloud_device_id = self.tuya_device_id(device)
                        # Definition metadata is optional. A denied or failing
                        # schema request must not suppress a working status API.
                        try:
                            device_definitions[device.id] = await self._client.get_cloud_device_definition(
                                cloud_device_id
                            )
                        except Exception as err:
                            _LOGGER.debug("Cloud DP definition unavailable for %s: %s", device.id, err)
                            device_definitions[device.id] = {}
                        try:
                            cloud_status = await self._client.get_cloud_device_status(
                                cloud_device_id
                            )
                            if isinstance(cloud_status.get("dps"), str):
                                cloud_status = {**cloud_status, **json.loads(cloud_status["dps"])}
                            elif isinstance(cloud_status.get("dps"), dict):
                                cloud_status = {**cloud_status, **cloud_status["dps"]}
                            for dp_id, dp_info in datapoints.items():
                                if str(dp_id) in cloud_status:
                                    cloud_status[dp_info["dpCode"]] = cloud_status[str(dp_id)]
                            # The current app uses DP 101 for PAW3300/3320
                            # quick feeding; older models use DP 201.
                            model = str(device.product_ctn or "").strip().upper().split("/")[0]
                            if model in {"PAW3300", "PAW3320"} and "101" in cloud_status:
                                cloud_status["feed_num"] = cloud_status["101"]
                            settings[device.id]["tuya_status"] = cloud_status
                        except Exception as err:
                            _LOGGER.debug("Cloud DP status unavailable for %s: %s", device.id, err)
                            # Never store None: a present-but-None tuya_status
                            # makes every entity's .get("tuya_status", {}).get()
                            # chain crash on add and drop the entity for the
                            # whole session. Fall back to an empty dict so
                            # entities load and simply report unavailable until
                            # the next successful cloud refresh.
                            settings[device.id]["tuya_status"] = tuya_status or {}

                    try:
                        firmware_info[device.id] = await self._client.get_cloud_firmware_info(
                            self.tuya_device_id(device)
                        )
                    except Exception as err:
                        _LOGGER.debug("Cloud OTA metadata unavailable for %s: %s", device.id, err)
                        firmware_info[device.id] = []
                    try:
                        product_firmware_info[device.id] = await self._client.get_product_firmware_info(
                            str(device.product_id or ""), device.id
                        )
                    except Exception as err:
                        _LOGGER.debug("Product OTA metadata unavailable for %s: %s", device.id, err)
                        product_firmware_info[device.id] = []
                    await self._save_ota_records(
                        device.id,
                        firmware_info[device.id] or product_firmware_info[device.id],
                    )

                    await asyncio.sleep(self.delay_between_calls)

                # Fetch meals
                try:
                    home_meals = await self._client.meals.get_meals(home)
                    meals.extend(home_meals)
                    _LOGGER.debug("Fetched %d meals for home %s", len(home_meals), home.id)
                except Exception as e:
                    _LOGGER.warning("Failed to fetch meals for home %s: %s", home.id, e)

                # Fetch invites
                try:
                    home_invites = await self._client.homes_manager.get_invites(home)
                    invites_by_home[home.id] = home_invites
                    _LOGGER.debug("Fetched %d invites for home %s", len(home_invites), home.id)
                except Exception as e:
                    _LOGGER.warning("Failed to fetch invites for home %s: %s", home.id, e)

                await asyncio.sleep(self.delay_between_calls)

            base_data = {}
            base_data["tuya_status"] = tuya_status
            base_data["device_definitions"] = device_definitions

            # Fetch discovery config
            try:
                discovery_config = await self._client.discovery_manager.get_discovery_config()
                base_data["discovery_config"] = discovery_config
            except Exception as e:
                _LOGGER.warning("Failed to fetch discovery config: %s", e)
                base_data["discovery_config"] = None

            return {
                "homes": homes,
                "home_devices": home_devices_by_home,
                "devices": devices,
                "meals": meals,
                "invites": invites_by_home,
                "events_by_home_and_type": events_by_home_and_type,
                "event_types": event_types,
                "settings": settings,
                "full_settings": full_settings,
                "firmware_info": firmware_info,
                "device_definitions": device_definitions,
                "product_firmware_info": product_firmware_info,
                "ota_history": self.ota_history,
                "base_data": base_data,
            }
        except ConfigEntryAuthFailed:
            # Re-raise auth failures so they can be handled properly
            raise
        except Exception as err:
            _LOGGER.exception("Error communicating with API: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up every Pet Series platform through the saved HomeID session."""
    from .homeid_client import HomeIDPetsClient

    client = HomeIDPetsClient(hass, entry)
    bridge = None
    beacons = None
    try:
        await client.initialize()
        _LOGGER.warning("HomeID Pet Series token ready: %s", entry.title)
        coordinator = PhilipsPetsSeriesDataUpdateCoordinator(
            hass, client, delay_between_calls=0.05,
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.warning("HomeID Pet Series data fetched: %s; %d homes; %d devices", entry.title, len(coordinator.data.get("homes", [])), len(coordinator.data.get("devices", [])))
        if not coordinator.data.get("devices"):
            from ..repair_helpers import report_missing_pet_devices

            report_missing_pet_devices(hass, entry)
            raise ConfigEntryNotReady("HomeID Pet Series API returned no matching devices")
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "client": client, "coordinator": coordinator,
        }
        bridge = PhilipsCameraBridgeManager(hass, entry, client, coordinator)
        await bridge.async_start()
        beacons = BeaconListener()
        await beacons.async_start()
        hass.data[DOMAIN][entry.entry_id].update(
            bridge=bridge, beacons=beacons, reload_signature=_entry_reload_signature(entry)
        )
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        # Preserve the existing one-portion button's registry identity/history.
        registry = er.async_get(hass)
        target = entry.data.get("tuya_device_id")
        if target:
            from .identity import migrate_feed_button_identity

            device = coordinator.data["devices"][0]
            migrate_feed_button_identity(registry, DOMAIN, target, device.id)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await async_setup_services(hass, client)
        await _async_setup_frontend(hass)
        from ..repair_helpers import clear_missing_pet_devices

        clear_missing_pet_devices(hass, entry)
        _LOGGER.warning("HomeID Pet Series ready: %s; %d device(s), %d platform(s)",
                        entry.title, len(coordinator.data["devices"]), len(PLATFORMS))
        return True
    except Exception:
        _LOGGER.exception("Full HomeID Pet Series setup failed for %s", entry.title)
        if bridge is not None:
            await bridge.async_stop()
        if beacons is not None:
            beacons.async_stop()
        await client.close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace cards and register the websocket command.

    Both are global rather than per-entry, so a second config entry must not
    register them twice.
    """
    if hass.data[DOMAIN].get("frontend_registered"):
        return
    hass.data[DOMAIN]["frontend_registered"] = True

    websocket.async_register(hass)

    integration = await async_get_integration(hass, DOMAIN)
    await JSModuleRegistration(hass, str(integration.version)).async_register()


async def async_setup_services(hass: HomeAssistant, client: PetsSeriesClient):
    """Set up custom services for Philips Pets Series."""
    if hass.data.get(DOMAIN, {}).get("services_registered"):
        return

    from homeassistant.helpers import config_validation as cv
    import voluptuous as vol
    from petsseries import HomeInviteRole

    async def handle_create_home(call):
        """Handle the create_home service."""
        name = call.data.get("name")
        if not name:
            _LOGGER.error("Service create_home: 'name' is required")
            return

        try:
            home = await client.homes_manager.create_home(name)
            _LOGGER.info("Created home: %s (%s)", home.name, home.id)
            # Trigger coordinator refresh to pick up new home
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                coordinator = entry_data.get("coordinator")
                if coordinator:
                    await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.exception("Failed to create home: %s", e)

    async def handle_send_home_invite(call):
        """Handle the send_home_invite service."""
        home_id = call.data.get("home_id")
        email = call.data.get("email")
        label = call.data.get("label")
        role_str = call.data.get("role", "MEMBER")

        if not all([home_id, email, label]):
            _LOGGER.error("Service send_home_invite: 'home_id', 'email', and 'label' are required")
            return

        try:
            role = HomeInviteRole(role_str)
        except (ValueError, TypeError) as e:
            _LOGGER.error("Invalid role '%s': %s", role_str, e)
            return

        # Find home object
        try:
            homes = await client.get_homes()
            home = next((h for h in homes if h.id == home_id), None)

            if not home:
                _LOGGER.error("Home with ID %s not found", home_id)
                return

            await client.homes_manager.send_invite(home, email, label, role)
            _LOGGER.info("Sent invite to %s for home %s", email, home.name)
            # Trigger coordinator refresh to pick up new invite
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                coordinator = entry_data.get("coordinator")
                if coordinator:
                    await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.exception("Failed to send invite: %s", e)

    async def handle_add_device(call):
        """Handle the add_device service."""
        home_id = call.data.get("home_id")
        product_ctn = call.data.get("product_ctn")

        if not all([home_id, product_ctn]):
            _LOGGER.error("Service add_device: 'home_id' and 'product_ctn' are required")
            return

        try:
            homes = await client.get_homes()
            home = next((h for h in homes if h.id == home_id), None)

            if not home:
                _LOGGER.error("Home with ID %s not found", home_id)
                return

            await client.devices_manager.add_device(home, product_ctn)
            _LOGGER.info("Added device %s to home %s", product_ctn, home.name)
            # Trigger coordinator refresh to pick up new device
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                coordinator = entry_data.get("coordinator")
                if coordinator:
                    await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.exception("Failed to add device: %s", e)

    async def handle_reset_device_filter(call):
        """Handle the reset_device_filter service."""
        # This one is tricky because we need the home and device object.
        # Targets are usually entity IDs.
        # We can iterate over the targets and map them to devices.
        # For simplicity, let's accept device_id and home_id as fields for now if not using targets,
        # but using targets is better.
        # Let's try to map from entity registry if possible, or iterate coordinator data.

        # NOTE: Simplified implementation expecting direct params or entity_id mapping
        # If calling from generic service, we might need to lookup device.
        # For now, let's just use home_id and device_id from fields to be safe.
        pass

    hass.services.async_register(DOMAIN, "create_home", handle_create_home)
    hass.services.async_register(DOMAIN, "send_home_invite", handle_send_home_invite)
    hass.services.async_register(DOMAIN, "add_device", handle_add_device)
    hass.data.setdefault(DOMAIN, {})["services_registered"] = True
    # hass.services.async_register(DOMAIN, "reset_device_filter", handle_reset_device_filter)


@callback
def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-key entities whose unique_id changed, keeping their history.

    The cloud-version sensor used a fixed unique_id that collided between
    accounts.  Renaming it in place preserves the existing entity instead of
    orphaning it and creating a duplicate alongside.
    """
    registry = er.async_get(hass)
    migrations = (("sensor", "philips_homeid_plus_api_version", f"{entry.entry_id}_api_version"),)
    for domain, old_unique_id, new_unique_id in migrations:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, old_unique_id)
        if entity_id is None:
            continue
        if registry.async_get_entity_id(domain, DOMAIN, new_unique_id) is not None:
            # The new id already exists; leave both alone rather than clashing.
            continue
        _LOGGER.debug("Migrating unique_id %s -> %s", old_unique_id, new_unique_id)
        registry.async_update_entity(entity_id, new_unique_id=new_unique_id)


@callback
def _async_remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete registry entries this integration no longer provides.

    Entities that stop being created are otherwise restored as permanently
    unavailable, so dropping a datapoint would leave dead rows behind.
    """
    registry = er.async_get(hass)
    stale_suffixes = tuple(f"_tuya_dp_{dp_id}" for dp_id in REMOVED_DP_SENSORS) + (
        "_number_food_weight",
        "_number_feed_abnormal",
    )
    stale_unique_ids: set[str] = set()

    # The MCU firmware sensor is only created for hardware that reports an MCU
    # module, so drop it for devices that do not -- but leave it untouched on
    # devices where it is still provided.
    coordinator = (hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}).get(
        "coordinator"
    )
    data = getattr(coordinator, "data", None) or {}
    for device in data.get("devices", []):
        # Only act on a definite answer.  Deleting a registry row throws away the
        # user's history, so "we could not read the module list this time" must
        # not be treated the same as "this feeder has no MCU".
        if not firmware.reports_ota_modules(coordinator, device.id):
            continue
        if not firmware.has_ota_module(coordinator, device, "mcu"):
            # Both the version sensor and the update entity are created only for
            # hardware that reports an MCU module, so both have to be dropped
            # for hardware that does not.
            stale_unique_ids.add(f"{device.id}_mcu_firmware_version")
            stale_unique_ids.add(f"{device.id}_mcu_firmware_update")

    for registry_entry in list(registry.entities.values()):
        if registry_entry.config_entry_id != entry.entry_id:
            continue
        if (
            registry_entry.unique_id.endswith(stale_suffixes)
            or registry_entry.unique_id in stale_unique_ids
            # Per-meal sensors stopped being created before 1.0.0; upgrades from
            # older versions still carry them as unavailable "Meal" entities.
            # Scheduled meals are exposed through the meal calendar instead.
            or registry_entry.unique_id.startswith("meal_")
        ):
            _LOGGER.debug("Removing stale entity %s", registry_entry.entity_id)
            registry.async_remove(registry_entry.entity_id)


def _entry_reload_signature(entry: ConfigEntry) -> tuple[dict, dict]:
    """Reload real configuration changes without unloading on token rotation."""
    return (
        {key: value for key, value in entry.data.items() if key != "cloud_refresh_token"},
        dict(entry.options),
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Keep calendars and sessions in place when only the saved token changes."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(runtime, dict):
        return
    current = _entry_reload_signature(entry)
    if runtime.get("reload_signature") == current:
        return
    runtime["reload_signature"] = current
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN][entry.entry_id]
        bridge = entry_data.get("bridge")
        if bridge is not None:
            await bridge.async_stop()
        beacons = entry_data.get("beacons")
        if beacons is not None:
            beacons.async_stop()
        client = entry_data["client"]
        await client.close()
        hass.data[DOMAIN].pop(entry.entry_id)
        global_keys = {"services_registered", "frontend_registered"}
        if not any(key not in global_keys for key in hass.data[DOMAIN]):
            # Last entry gone: drop the global registration flags.  The Lovelace
            # resource is deliberately left in place -- removing the integration
            # is what should remove the cards, not reloading it.
            for key in global_keys:
                hass.data[DOMAIN].pop(key, None)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the cards' Lovelace resource when the last entry is removed."""
    if any(
        other.entry_id != entry.entry_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        return
    integration = await async_get_integration(hass, DOMAIN)
    await JSModuleRegistration(hass, str(integration.version)).async_unregister()
