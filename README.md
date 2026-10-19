# Philips HomeID Plus

An unofficial Home Assistant custom integration that brings several Philips HomeID product families together under one integration.

Current support includes:

- Philips HomeID appliances supported by the upstream HomeID integration.
- Philips Pet Series feeders, including PAW3320/02 and PAW5320/02.
- Philips air purifiers and humidifiers supported through local encrypted CoAP.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with, endorsed by, or supported by Philips, Versuni, or the developers of the official Philips HomeID app.

## Installation with HACS

1. Open HACS in Home Assistant.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/samyhch/homeassistant-philips-homeid-plus`.
4. Select **Integration** as the category.
5. Search for **Philips HomeID Plus** and install it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration** and select **Philips HomeID Plus**.

## Manual installation

Copy `custom_components/philips_homeid_plus` into the `custom_components` directory of your Home Assistant configuration, then restart Home Assistant.

## Supported device paths

### HomeID appliances

Uses the HomeID integration foundation for compatible local devices and supported HomeID cloud-relay devices.

Explicit built-in Airfryer model profiles:

- HD9200
- HD9255
- HD9280
- HD9285
- HD9875
- HD9876
- HD9880

HomeID may also discover additional compatible appliances through its generic local or cloud-relay paths. Those models should be reported with diagnostics so they can be added to the verified list.

### Pet Series feeders

Pet Series devices use the HomeID account session. A single HomeID sign-in can discover the compatible feeders associated with that account. The integration exposes feeder controls, status sensors, schedules, diagnostics, and the entities supported by the adapted Pet Series implementation.

The initial tested feeder models are:

- PAW3320/02
- PAW5320/02

The adapted Pet Series code also contains compatibility handling for the PAW3300 family, but it is not part of the initial verified test set.

### Air purifiers and humidifiers

Compatible devices communicate directly over the local network using encrypted CoAP. Availability depends on the model, firmware, and local network connectivity. Some Philips firmware versions may stop responding to CoAP until the device is power-cycled.

Built-in air-treatment model profiles:

- **AC series:** AC0850/11, AC0850/20, AC0850/31, AC0850/41, AC0850/70, AC0850/81, AC0850/85, AC0950, AC0951, AC1214, AC1715, AC2210, AC2220, AC2221, AC2729, AC2889, AC2936, AC2939, AC2958, AC2959, AC3021, AC3033, AC3036, AC3039, AC3055, AC3059, AC3210, AC3220, AC3221, AC3259, AC3360/11, AC3420, AC3421, AC3737, AC3829, AC3836, AC3854/50, AC3854/51, AC3858/50, AC3858/51, AC3858/83, AC3858/86, AC4220, AC4221, AC4231, AC4236, AC4550, AC4558, AC5659, AC5660
- **AMF series:** AMF765, AMF870
- **CX series:** CX3120, CX3550, CX5120
- **HU series:** HU1509, HU1510, HU4209, HU4210, HU5710

Some AC0850 variants advertise an `AWS_Philips_AIR` or `AWS_Philips_AIR_Combo` identifier; both identifiers are included in the integration's model mapping.

This list means that a model profile exists in the integration. Exact entities and controls vary by model and firmware, and not every listed model has been physically verified by this project's maintainer.

## Upgrading from the original integrations

Do not configure two integrations against the same device at the same time. In particular, a Philips air purifier may support only one active long-lived CoAP observer. Back up your Home Assistant configuration before migrating existing entries.

Automatic cross-domain migration from the three upstream integrations is not included in the public `v0.1.0` release. Existing users should remove the old entry and add the device to Philips HomeID Plus, or wait for a documented migration tool in a later release.

## Help and development

See [troubleshooting and known limitations](docs/TROUBLESHOOTING.md) for setup,
availability and command errors, and [contributing](CONTRIBUTING.md) for local
validation and regression tests.

## Project origins and acknowledgements

Philips HomeID Plus combines and adapts functionality from three existing Home Assistant integrations:

- [Philips HomeID](https://github.com/renaudallard/homeassistant_philips_homeid) by Renaud Allard — the foundation for HomeID discovery, authentication, local control, and cloud communication.
- [Philips Pet Series](https://github.com/AboveColin/HA-Philips-Pet-Series) by AboveColin — the foundation for Pet Series entities, services, device controls, and supporting functionality.
- [Philips AirPurifier CoAP](https://github.com/kongo09/philips-airpurifier-coap) by kongo09 and contributors — the foundation for encrypted local CoAP support for air purifiers and humidifiers.

The original projects remain the work of their respective authors and contributors. This project adapts and unifies their functionality under one Home Assistant integration. See [NOTICE.md](NOTICE.md) and the retained license notices for details.

Please report problems caused by this combined integration in this repository rather than in the upstream projects, unless the issue has been independently reproduced there.

## Privacy and security

- Never include passwords, tokens, diagnostics, serial numbers, device IDs, or public IP addresses in an issue.
- Redact personal data before attaching Home Assistant logs or diagnostics.
- Credentials remain in your Home Assistant configuration and are not part of this repository.

## License

The integration is distributed under the MIT License. Incorporated portions remain subject to their original compatible license notices, including the BSD 2-Clause notice for Philips HomeID. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
