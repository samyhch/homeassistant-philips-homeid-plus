# Device verification matrix

This distinguishes inherited model profiles from physical verification. A model
profile is not evidence that every feature works on every firmware. No firmware
version has yet been recorded for the owner's devices in a reproducible test
report; do not interpret a blank firmware cell as an unrestricted guarantee.

| Model | Type | Firmware verified | Local transport | Cloud transport | Evidence and limitations |
|---|---|---|---|---|---|
| PAW3320/02 | Feeder, no camera | Not recorded | Not verified | HomeID/Tuya | Owner previously confirmed one-portion feeding; latest status/command fixes have mock tests only. Volume/scheduled portions remain unverified. |
| PAW5320/02 | Camera feeder | Not recorded | Camera bridge is not local feeding | HomeID/Tuya | Owner previously confirmed one-portion feeding; camera snapshots depend on events and permissions. Latest branch not physically tested. |
| AC0951/13 | Air purifier | Not recorded | CoAP | Not implemented for this profile | Owner's installation had valid recorded states; fixture/model construction checks do not replace physical tests. |
| AC3360/11 | Air purifier | Not recorded | CoAP | Not implemented for this profile | Owner's installation had valid recorded states; commands and restart regression require physical verification. |
| AC3420/10 | Purifier/humidifier | Not recorded | CoAP | Not implemented for this profile | Owner's installation had valid recorded states; available sensors depend on status keys. |
| HU5710/00 | Humidifier | Not recorded | CoAP | Not implemented for this profile | Owner's installation had valid recorded states; no independent cloud fallback. |

The complete inherited compatibility lists are in [README](README.md#supported-device-paths).
Models on those lists but not in this matrix are **profile-supported, not
physically verified by this project**. They include other HomeID appliances,
air purifiers, humidifiers, fans and heaters. PAW3300 compatibility is inherited
and is not part of the verified hardware set.

To add verification, use the device-support issue template. Include exact CTN,
firmware, integration/HA versions, which reads and commands were tested, and a
reviewed diagnostic export. Remove credentials, device IDs, serial numbers,
network addresses, personal home names and camera links. Never post raw storage
files or an APK containing account/session data.
