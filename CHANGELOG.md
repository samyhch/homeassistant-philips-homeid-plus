# Changelog

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
