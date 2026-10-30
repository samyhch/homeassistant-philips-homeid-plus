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

When adding another device, select the saved HomeID session represented by an
existing device. Entries sharing a refresh token are grouped into one choice;
Air+ sessions are kept separate because their tokens have a different audience.
You can explicitly select the normal email/OTP login for a different account.
Saved-session discovery first uses HomeID and falls back to the IoT registry
when HomeID lists no devices.

Complete the reauthentication prompt in Devices & services with your HomeID email
and verification code. Do not create a second account entry to work around an
authentication error. Never include the verification code or tokens in an issue.

## Tuya command rejected

Check whether the same action works in HomeID. Include the model, firmware,
action name and error code in a bug report, together with the integration version.
Discovery access alone does not establish permission to execute every command.
Do not repeatedly retry feeding or firmware commands when their outcome is unknown.

## Missing feeder calendar or dispensing history

Version 0.1.4 reads schedules and history from the current HomeID production Pet
service and translates backend identifiers to existing Home Assistant identities.
An older endpoint can return empty lists without reporting an authentication
failure. Update the integration, restart Home Assistant once to load the new
Python modules, and check the affected entry's calendar and last-dispense data.
Do not delete and recreate the entry or manually change device identifiers.

If data are still missing, confirm that the schedule/history exists in the
official HomeID app for the same account and feeder. A genuinely empty schedule
or history is valid, and the integration does not create substitute meals or
infer that feeding occurred. Include the model, firmware, integration version
and sanitized diagnostics when reporting a persistent discrepancy.

The schedule and history reads do not validate physical feeding or calendar
writes. Do not create or modify meals merely to test recovery.

## Repeated feeder setup during token refresh

Normal refresh-token rotation no longer reloads feeder entries in 0.1.4, so
calendars and HTTP sessions can remain loaded. Changes to actual configuration
or options still reload the entry. A brief missing-entity warning during a
deliberate reload does not by itself mean the calendar has been lost.

If repeated setup continues without configuration changes, inspect the entry's
authentication and setup status. Report the integration version and sanitized
timestamps; never share token values. Reauthentication is appropriate for an
explicit authentication failure, not as a general response to every timeout.

## Camera bridge fails or repeatedly restarts

The feeder's camera transport has a separate lifecycle from feeding status and
meal data. Version 0.1.4 reserves different RTSP ports across entries and checks
camera capability at each stream/start path. PAW3320 has no camera and must not
start a bridge. Existing unsupported camera registry records are not deleted
automatically; disable them if they are still shown as unavailable.

A bridge startup failure no longer prevents an always-mode feeder entry from
loading. Retries back off, and repeated failures introduce a cooldown. Opening
a viewer does not bypass that cooldown. Check the camera mode and whether the
official app can view the camera, then collect sanitized diagnostics if the
failure continues. Do not repeatedly reload the entry to force retries.

An address-in-use error identifies a local port conflict; an exit status alone
does not establish failed camera hardware or an expired account. Report the
model, integration version and redacted error category, without stream URLs,
credentials or device identifiers. No successful video stream is implied by a
healthy feeder status sensor or an open RTSP port.

## Collecting diagnostics

Download diagnostics from the affected integration entry. Diagnostic exports
remove credentials, recognized personal identifiers and stream/download URLs
recursively, including failed setup and local CoAP entries. Review the file
before sharing: newly introduced vendor fields may contain personal information.
Camera connection URLs and ready-to-use recorder configurations are deliberately
excluded from exported diagnostics.

## Known limitations

### Unavailable after restart

First inspect the entry's setup/reauthentication status and download diagnostics.
The `connection` section separates the configured transport, availability, last
observed successful update and a bounded failure reason. Cached CoAP status is
not counted as a new successful update. A last success timestamp is not proof
that a physical command succeeded. For a local outage check DHCP/IP and competing
observers; for a cloud outage test the same account in HomeID. Reload the affected
entry once after correcting the cause instead of repeatedly restarting all HA.

### Migrating from legacy integrations

Back up HA and record entity IDs, unique IDs and device associations first.
Disable the old entry, test the new entry, and verify automations/history before
removing anything. Do not edit `.storage` while HA runs. The integration's own
legacy one-portion button migration changes its unique ID in place and refuses
to overwrite an existing target identity; it is not a universal cross-domain
migration. Legacy entries are never disabled automatically by a conflict warning.

### Authentication/API changes

Keep the email/OTP flow; do not supply Tuya developer credentials to work around
a HomeID permission error. Report exact model/firmware, operation and sanitized
error diagnostics. A schema-metadata failure is now independent of status reads.
Permission denied does not prove an expired session. Camera/OTA/history APIs may
have different permissions from basic feeding.

### Health and optional sensors

Transport health is exported in diagnostics. Account Options can change the
inventory interval from 1 to 60 minutes; this does not alter device polling.
The account's add-device action uses the saved HomeID session. Device entries
still have their own lifecycle, so use HA's native disable/re-enable option for
individual devices. No general cloud/local failover is advertised: it must be
verified separately per model and must never duplicate a feed action.

### Remaining limitations

- Entity availability depends on the model, firmware and upstream API permissions.
- Local CoAP appliances and cloud-connected feeders use different transports;
  a cloud outage does not imply local CoAP should be unavailable.
- Existing entries remain per-device. Shared HomeID session handling does not yet
  automatically add or remove devices. The optional central account entry provides
  inventory counts and starts device onboarding with the same saved session.
- Cross-integration migration preserving entity registry identities requires a
  separately tested migration process. Removing and recreating entries can change
  entity IDs. Back up your configuration before migrating.
- Built-in model profiles are not a claim that every device was physically tested.
- PAW3320 has no camera: camera, snapshot and camera-only controls are not
  created for this model (including regional CTNs such as PAW3320/02). Unknown
  models retain the existing behavior. Missing cloud status alone is not used
  to remove feeding or volume controls. Existing registry records are not
  deleted automatically; previously created unsupported entities may remain
  listed as unavailable and can be disabled manually without deleting history.
