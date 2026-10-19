"""Run isolated compatibility checks with installed HA and integration dependencies.

Usage: python -B scripts/ha_smoke.py /path/to/candidate/repository
Use a separate Python process. Cloud and platform setup are mocked; no real
config entries, credentials or devices are read or controlled.
"""

import asyncio, ast, importlib, pathlib, sys, types
from types import MappingProxyType
root = pathlib.Path(sys.argv[1]).resolve()
namespace = types.ModuleType("custom_components")
namespace.__path__ = [str(root / "custom_components")]
sys.modules["custom_components"] = namespace
prefix = "custom_components.philips_homeid_plus"
for name in ("config_flow", "account_hub", "account_sensor", "diagnostics", "sensor"):
    module = importlib.import_module(prefix + "." + name)
    assert str(root) in module.__file__, module.__file__
    print("REAL_HA_IMPORT_OK", name)
for path in (root / "custom_components").rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
async def main():
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry, ConfigEntries, ConfigEntryState
    flow_module = importlib.import_module(prefix + ".config_flow")
    hub_module = importlib.import_module(prefix + ".account_hub")
    sensor_module = importlib.import_module(prefix + ".account_sensor")
    hass = HomeAssistant(str(root / "ha-fixture"))
    # An isolated process has no loader bootstrap; deprecation reporting still
    # expects the integration cache to exist when an integration frame is found.
    hass.data.setdefault("integrations", {})
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(version=1, minor_version=1, domain="philips_homeid_plus",
        title="Fixture device", data={"cloud_refresh_token":"fixture-only"},
        options={}, source="user", unique_id="fixture-device",
        discovery_keys=MappingProxyType({}), subentries_data=[])
    original_id = entry.unique_id
    flow = flow_module.PhilipsHomeIDConfigFlow()
    flow.hass = hass
    flow.flow_id = "fixture-flow"
    flow.context = {"source":"user"}
    flow._async_current_entries = lambda: [entry]
    result = await flow.async_step_cloud_email()
    assert result["step_id"] == "saved_account"
    result["data_schema"]({"account": entry.entry_id})
    print("REAL_HA_SAVED_ACCOUNT_SCHEMA_OK")
    flow._cloud_tokens = {"refresh_token":"fixture-only"}
    result = await flow.async_step_account_hub()
    assert result["step_id"] == "account_hub"
    result["data_schema"]({"name":"Fixture account"})
    result = await flow.async_step_account_hub({"name":"Fixture account"})
    assert result["data"]["is_homeid_account"]
    assert entry.unique_id == original_id
    print("REAL_HA_ACCOUNT_CREATE_RESULT_OK")
    coordinator = hub_module.HomeIDAccountCoordinator(hass, entry)
    coordinator.async_set_updated_data({"discovered_devices": 3, "configured_devices": 1})
    sensor = sensor_module.HomeIDAccountSensor(coordinator, entry, "discovered_devices")
    assert sensor.native_value == 3
    options = hub_module.HomeIDAccountOptionsFlow()
    options.hass = hass
    menu = await options.async_step_init()
    assert menu["step_id"] == "account"
    print("REAL_HA_ACCOUNT_SENSOR_AND_OPTIONS_OK")
    await coordinator.async_shutdown()
    from unittest.mock import AsyncMock, patch
    package = importlib.import_module(prefix)
    repairs = importlib.import_module(prefix + ".repair_helpers")
    entry = ConfigEntry(version=1, minor_version=1, domain="philips_homeid_plus",
        state=ConfigEntryState.SETUP_IN_PROGRESS, title="Fixture account", data={"is_homeid_account":True, "cloud_refresh_token":"fixture-only"},
        options={}, source="user", unique_id="homeid_account_fixture",
        discovery_keys=MappingProxyType({}), subentries_data=[])
    api = types.SimpleNamespace(
        get_appliances_via_homeid=AsyncMock(return_value=[{"name":"Fixture appliance"}]),
        get_devices=AsyncMock(return_value=[]), close=AsyncMock())
    forward = AsyncMock()
    unload = AsyncMock(return_value=True)
    with patch.object(repairs, "report_setup_issue"), patch.object(repairs, "clear_setup_issues"), patch.object(hub_module, "PhilipsCloudAPI", return_value=api), patch.object(
        hub_module, "homeid_tokens", AsyncMock(return_value={"access_token":"fixture-only"})
    ), patch.object(ConfigEntries, "async_entries", return_value=[entry]), patch.object(
        ConfigEntries, "async_forward_entry_setups", forward
    ), patch.object(ConfigEntries, "async_unload_platforms", unload):
        assert await package.async_setup_entry(hass, entry)
        runtime = hass.data["philips_homeid_plus"][entry.entry_id]
        assert runtime["account_coordinator"].data["discovered_devices"] == 1
        assert runtime["account_coordinator"].data["configured_devices"] == 0
        entities = []
        await sensor_module.async_setup_entry(hass, entry, entities.extend)
        assert len(entities) == 2
        assert entities[0].native_value == 1
        assert await package.async_unload_entry(hass, entry)
        assert entry.entry_id not in hass.data["philips_homeid_plus"]
        assert forward.await_count == 1 and unload.await_count == 1
        api.close.assert_awaited_once()
    print("REAL_HA_SETUP_UNLOAD_AND_PLATFORM_DISPATCH_OK")
    # Construct the actual four model profiles and exercise controls against
    # AsyncMocks only. No production entry/device is read or connected.
    from unittest.mock import Mock
    air = importlib.import_module(prefix + ".airpurifier.philips")
    air_const = importlib.import_module(prefix + ".airpurifier.const")
    for model in ("AC0951", "AC3360/11", "AC3420", "HU5710"):
        cls = air.model_to_class[model]
        status = {air_const.PhilipsApi.MODEL_ID: model,
                  air_const.PhilipsApi.WIFI_VERSION: "fixture-1",
                  air_const.PhilipsApi.DEVICE_ID: "fixture-device"}
        client = types.SimpleNamespace(set_control_value=AsyncMock(), set_control_values=AsyncMock())
        coordinator = types.SimpleNamespace(status=status, client=client, last_update_success=True)
        runtime = types.SimpleNamespace(coordinator=coordinator, latest_status=status,
            device_information=types.SimpleNamespace(model=model, name="Fixture", device_id="fixture-device", mac=None))
        entity = cls(hass, entry, runtime)
        entity._handle_coordinator_update = Mock()
        assert entity.available
        coordinator.last_update_success = False
        assert not entity.available
        coordinator.last_update_success = True
        await entity.async_turn_on()
        client.set_control_value.assert_awaited_once_with(entity.KEY_PHILIPS_POWER, entity.STATE_POWER_ON)
        assert entity.is_on
        await entity.async_turn_off()
        assert not entity.is_on
        assert entity.unique_id == f"{model}-fixture-device"
        if model in ("AC3420", "HU5710"):
            platform = importlib.import_module(prefix + ".airpurifier.humidifier")
            hass.data.setdefault("philips_homeid_plus", {})[entry.entry_id] = runtime
            humidifiers = []
            await platform.async_setup_entry(hass, entry, lambda items, **kwargs: humidifiers.extend(items))
            assert humidifiers, model
        print("REAL_HA_MODEL_FIXTURE_OK", model)

    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    import logging
    coordinator = DataUpdateCoordinator(hass, logging.getLogger(__name__), name="fixture-pet", config_entry=entry)
    pet_client = types.SimpleNamespace(auth=types.SimpleNamespace(id_token="fixture"), tuya_client=None,
                                     publish_cloud_dps=AsyncMock())
    home = types.SimpleNamespace(id="fixture-home")
    for model, dp in (("PAW3320/02", "101"), ("PAW5320/02", "201")):
        device = types.SimpleNamespace(id="fixture-pet", product_ctn=model, name="Fixture feeder")
        coordinator.async_set_updated_data({"homes": [home], "home_devices": {home.id: [device]},
            "settings": {device.id: {"tuya_status": {dp: 0, "feed_num": 0}}}})
        coordinator.tuya_device_id = lambda _: "fixture-target"
        coordinator.async_request_refresh = AsyncMock()
        hass.data["philips_homeid_plus"][entry.entry_id] = {"client": pet_client, "coordinator": coordinator}
        platform = importlib.import_module(prefix + ".pet_series.number")
        numbers = []
        await platform.async_setup_entry(hass, entry, numbers.extend)
        number = next(item for item in numbers if item._dp_code == "feed_num")
        assert number.available
        assert number.unique_id == "fixture-pet_number_feed_num"
        await number.async_set_native_value(2)
        pet_client.publish_cloud_dps.assert_awaited_with("fixture-target", {"201": 2})
        print("REAL_HA_FEED_NUMBER_FIXTURE_OK", model)
    await coordinator.async_shutdown()
    # The actual CoAP coordinator must release its timer and observer on unload.
    coap = importlib.import_module(prefix + ".airpurifier.coordinator")
    client = types.SimpleNamespace(get_status=AsyncMock(return_value=({"fixture": 1}, 60)), shutdown=AsyncMock())
    coordinator = coap.Coordinator(hass, client, "192.0.2.1", None)
    await coordinator.async_first_refresh()
    assert coordinator.last_update_success
    observer = asyncio.create_task(asyncio.Event().wait())
    coordinator._task = observer
    await coordinator.shutdown()
    assert observer.cancelled()
    client.shutdown.assert_awaited_once()
    print("REAL_HA_COAP_SHUTDOWN_FIXTURE_OK")
asyncio.run(main())
