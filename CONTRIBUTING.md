# Contributing

Run these checks from the repository root using Python 3.13 or 3.14:

```sh
python scripts/validate.py
python -B -m unittest discover -s tests -v
```

The syntax validator uses ast.parse and does not write protected __pycache__
directories. The initial regression suite needs only the Python standard library.
Its backend tests stub Home Assistant imports and exercise diagnostic routing,
account token rotation, concurrency and selected config-flow paths. Flow tests
stub form/schema imports; they do not replace testing actual Home Assistant form
rendering, schema validation, entry lifecycle or real devices.

GitHub Actions runs the suite on both Python versions. HACS and Hassfest run
separately. Changes to authentication, commands, entry migration or identifiers
need regression coverage and testing on the affected device families.

Never include credentials, real device identifiers, camera URLs or customer logs
in test fixtures. Use reserved example addresses and fictitious credentials.
Preserve LICENSE, NOTICE.md and upstream notices when adapting code.

Test a candidate release on an isolated Home Assistant installation before
publishing. With Home Assistant and the integration dependencies installed, run
`python -B scripts/ha_smoke.py /path/to/candidate/repository` in a separate Python
process. This checks actual HA imports, config forms and schema validation,
account creation results, sensor construction, and account setup/unload dispatch.
Cloud replies and platform forwarding are mocked; it does not test physical
devices or persist entries into the running HA instance. The script has been
verified with Home Assistant 2026.10.2 using fixture credentials only.

Test actual device behavior separately before
updating a production installation. Keep a backup of config entries, entity and
device registries. Confirm that entity IDs and history survive a migration.
