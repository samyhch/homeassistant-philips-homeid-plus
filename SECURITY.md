# Security and privacy

HomeID cloud credentials are stored in Home Assistant config entries. Local
CoAP appliances communicate on the local network; cloud appliances and feeders
contact Philips/HomeID and their Tuya service. A central account inventory uses
the existing HomeID email/OTP authentication, not a Tuya developer account.

Downloaded diagnostics recursively redact recognized credentials, identifiers,
network addresses and signed/camera URLs. Review every export before sharing:
vendor APIs can introduce new personal fields. Device states/event attributes,
Home Assistant backups, debug logs and recorder data are not diagnostic exports
and may contain personal data. Do not publish them without review.

The integration does not provide analytics or send diagnostics to this project's
maintainers. This does not prevent the vendor's own cloud processing. Camera
bridges and local streams should be restricted to trusted networks; do not expose
them, SSH or Home Assistant directly to the internet. Prefer Home Assistant's
supported remote access or a VPN.

Feeding commands are never retried automatically after an ambiguous failure.
Check the physical device before repeating one. Firmware entities are read-only:
use the official app to install firmware. Automatic fallback must not issue the
same feeding command through another transport.

Report a vulnerability through the repository's private GitHub security advisory
facility if enabled. If unavailable, open an issue asking for a private contact
without including exploit details or secrets. Revoke any exposed credentials.
The project is provided without warranty; no model is claimed safe for unattended
feeding solely because a command returned success.
