# Troubleshooting

## No matching Pet devices

If setup reports that the HomeID Pet Series API returned no matching devices,
open the official HomeID app using the same account and check that the feeder
appears in the expected home. Confirm that it can be controlled in the app.
If ownership or sharing changed, restore access in HomeID before reloading the
integration entry. A missing device is not necessarily an expired login.

Home Assistant retries setup automatically. A Repair notice identifies the
affected entry and clears after successful setup. If you intentionally removed
the feeder from HomeID, remove its corresponding integration entry from Home
Assistant. Do not manually edit Home Assistant storage files.

## Unavailable air purifier or humidifier

Confirm that the device is powered and reachable at its configured local IP.
Use a DHCP reservation to keep the address stable. Check that another integration
is not observing the same purifier: some devices permit only one CoAP observer.
Disable the competing entry and reload Philips HomeID Plus.

If a known device stops answering CoAP after a firmware or network change,
power-cycle the appliance and reload its entry. Collect diagnostics if this
continues. Do not repeatedly restart Home Assistant to recover one appliance.

## Expired HomeID login

Complete the reauthentication prompt in Devices & services with your HomeID email
and verification code. Do not create a second account entry to work around an
authentication error. Never include the verification code or tokens in an issue.

## Tuya command rejected

Check whether the same action works in HomeID. Include the model, firmware,
action name and error code in a bug report, together with the integration version.
Discovery access alone does not establish permission to execute every command.
Do not repeatedly retry feeding or firmware commands when their outcome is unknown.

## Collecting diagnostics

Download diagnostics from the affected integration entry. Diagnostic exports
remove credentials, recognized personal identifiers and stream/download URLs
recursively, including failed setup and local CoAP entries. Review the file
before sharing: newly introduced vendor fields may contain personal information.
Camera connection URLs and ready-to-use recorder configurations are deliberately
excluded from exported diagnostics.

## Known limitations

- Entity availability depends on the model, firmware and upstream API permissions.
- Local CoAP appliances and cloud-connected feeders use different transports;
  a cloud outage does not imply local CoAP should be unavailable.
- Existing entries remain per-device. Shared HomeID session handling does not yet
  provide an account hub with automatic addition/removal of every device.
- Cross-integration migration preserving entity registry identities requires a
  separately tested migration process. Removing and recreating entries can change
  entity IDs. Back up your configuration before migrating.
- Built-in model profiles are not a claim that every device was physically tested.
