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
    entry = ConfigEntry(version=1, minor_version=1, domain="philips_homeid_plus",
        state=ConfigEntryState.SETUP_IN_PROGRESS, title="Fixture account", data={"is_homeid_account":True, "cloud_refresh_token":"fixture-only"},
        options={}, source="user", unique_id="homeid_account_fixture",
        discovery_keys=MappingProxyType({}), subentries_data=[])
    api = types.SimpleNamespace(
        get_appliances_via_homeid=AsyncMock(return_value=[{"name":"Fixture appliance"}]),
        get_devices=AsyncMock(return_value=[]), close=AsyncMock())
    forward = AsyncMock()
    unload = AsyncMock(return_value=True)
    with patch.object(hub_module, "PhilipsCloudAPI", return_value=api), patch.object(
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
asyncio.run(main())
