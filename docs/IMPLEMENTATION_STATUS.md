# Improvement checklist — 2026-10-20

This is a candid progress record, not a release certification. The working Home
Assistant installation has not been replaced or restarted for these changes.

| Proposal | Implemented in the draft branch | Remaining before calling it complete |
|---|---|---|
| Tests | 83 unit/regression tests; OTP/reauth paths, token rotation, selected commands, identity migration, CoAP cancellation, transport/errors, privacy; real HA fixture smoke for all six owner models | Full config-flow coverage; all legacy platforms; real registry/recorder migration and whole-HA restart tests; supervised hardware verification. Measured full-source unit coverage is 6%, **not 95%**. |
| CI | pytest/coverage artifacts on 3.13/3.14, correctness Ruff, baseline mypy, JSON/translation-placeholder/YAML checks, HA 2026.10.2 fixture smoke, HACS/Hassfest, release ZIP/version checks, Python-tooling and Actions Dependabot | Full style/type coverage; automated monitoring of manifest-pinned vendor runtime dependencies, beyond the HA smoke requirements file. |
| Repairs | Missing feeder, expired setup authentication, missing HomeID session, setup/runtime local connection failure, active exact-identity legacy conflict | Evidence-based model/firmware incompatibility detection; more complete runtime cloud-auth classification. |
| Transport health | Diagnostic transport, availability, last successful update, bounded failure reason; stale CoAP data no longer implies healthy connection after a detected timeout | Separate cloud/local health entities and verified per-model automatic fallback. No command is duplicated through a fallback path. |
| Capabilities | PAW3320 camera exclusion; diagnostic/config categories and optional raw history sensor | Complete authoritative schema-driven model capabilities and remaining units/classes review. |
| Account hub | Saved-session reuse, shared refresh, central inventory entry, add-device routing, refresh, adjustable inventory interval | Automatically managed device subentries under one account, selection/exclusion, coordinated migration of old entries, per-device local/cloud and advanced-entity options. Existing entries/IDs remain intact. |
| Errors | English/Bulgarian translated errors for Pet button/number/select/switch and all CoAP writes; invalid input rejected before writes; no feeding retries | Audit other HomeID/MQTT actions and broader vendor error shapes. |
| Feed automations | Existing portion control/events/last-next meal/read-only calendar; optional observed-feeding count; problem/offline notification blueprints | Verified daily **portion** units/completeness, editable calendar, supervised confirmation of portion command mapping. No unattended emergency feeding is supplied. |
| Air dashboard | Standard-card YAML example and sustained PM2.5 blueprint | User entity selection and visual/device testing; absent model sensors must be removed. |
| Firmware | Read-only current/offered versions, no INSTALL feature, regression tests | Verification of actual OTA permissions/versions for each physical model. |
| Device matrix | Exact six owner models, explicit firmware/evidence gaps, inherited-profile distinction, issue template | Recorded firmware and feature-by-feature hardware evidence. |
| Troubleshooting | Restart/unavailable, permissions, CoAP, conflicts, session/API changes, migration limits and security docs | Verification of all procedures on a disposable full HA instance. |
| HACS default catalog | Release/checklist, existing HACS configuration/assets, security/privacy documentation | Stable tested release, topics/brand verification, external submission and acceptance. No submission claimed. |

Do not close the remaining items merely to make the checklist green. In
particular, a bounded event list is not proof of daily food totals; inherited
calendar write APIs are not proof that writes still work after the HomeID
migration; and reading CoAP with a second observer may disrupt a real device.
