# Changelog

## 0.1.4 — 2026-10-30

Feeder telemetry and camera-bridge reliability maintenance. The broader
improvement roadmap remains open.

- Read feeder schedules and history from the current HomeID production service,
  accepting the current meal fields and translating backend device ownership
  without changing established Home Assistant entity identities.
- Discover account homes before generating fallback devices, keep each feeder
  with its actual home, and retain errors instead of inventing replacement
  devices when discovery is incomplete.
- Keep feeder entries, calendars and sessions loaded when only the saved refresh
  token rotates; real configuration and option changes still reload the entry.
- Allocate distinct camera-bridge ports across entries, enforce camera capability
  checks at stream/start entry points, and preserve retry backoff across failed
  child processes. Stop retry/monitor tasks and owned HTTP sessions on unload.
- Keep feeder setup available when an always-on camera bridge cannot start.
  Skip legacy settings resources only after a confirmed HTTP 400/404 for a
  synthetic Tuya-only device; authentication, network and server failures remain
  visible.

### Verification and limits

Runtime read checks on PAW3320/PAW5320 restored existing meal calendars and
dispensing history while retaining established entity IDs through restart and
refresh. Regression coverage exercises identity selection, production API
adapters, token-only updates and bridge lifecycle behavior.

No physical feeding command, schedule write or successful live video frame was
verified for this release. Existing portion-control behavior remains unchanged;
no automatic retries of feeding commands or firmware installation are enabled.
This is not certification of every model, firmware or remaining roadmap item.

Back up Home Assistant before updating. Do not delete and recreate entries for
a normal upgrade. To roll back, restore the previous integration version and
the matching pre-update HA backup if configuration or registry data also need
restoring.

## 0.1.3 — 2026-10-20

Maintenance and account-session improvements; this is not the completion of the
full improvement roadmap.

- Reuse saved HomeID sessions, serialize token rotation, keep Air+ sessions
  separate, and provide an optional account inventory manager with refresh and
  inventory interval options. Existing device entries and identities remain.
- Redact credentials/identifiers/URLs recursively in diagnostics, including
  failed setup; add transport health and actionable setup/connectivity Repairs.
- Translate common feeder and CoAP command errors into English/Bulgarian and
  reject invalid numeric values before issuing commands. Never retry feeding.
- Do not create camera-only entities for the camera-less PAW3320. Read feeder
  status even when optional definition metadata cannot be fetched.
- Correct CoAP offline availability, cancel observer/reconnect/timer tasks on
  unload, and retain the runtime if platform unload fails.
- Add optional disabled-by-default observed-feeding-event counts. These are not
  authoritative daily portion totals and do not infer `mealAmount` units.
- Add 83 regression tests, Python 3.13/3.14 CI, real HA 2026.10.2 fixture smoke,
  coverage reports, correctness lint/type baselines, translation/YAML checks,
  release archives, notification blueprints, dashboard example and device matrix.

### Explicitly excluded or unchanged

- The existing **Dispense portions now** command register is unchanged. The
  proposed PAW3320 N-portions remapping is withheld pending supervised testing;
  the physical feeder button is unaffected.
- No automatic account/subentry migration, editable meal calendar, general
  local/cloud failover or unattended emergency feeding.
- Unit coverage is approximately 6% of the full inherited code, not 95%.
  Compatibility smoke uses fixtures/mocked commands, not physical appliances.
- Firmware installation remains disabled; use the official app.

Back up HA before updating. Do not run a legacy CoAP integration against the same
appliance simultaneously. HACS default-catalog inclusion is not claimed.
