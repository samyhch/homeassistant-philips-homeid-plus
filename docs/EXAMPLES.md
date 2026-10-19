# Dashboards and automations

`examples/air-quality-dashboard.yaml` is a standard-card dashboard template.
Replace its illustrative entity IDs with yours and remove unsupported sensors.
The gauge colors are configurable UI thresholds, not a medical assessment.

Blueprints in `blueprints/automation/` provide sustained PM2.5 activation,
feeder problem notifications, and offline notifications. Copy/import a blueprint
and explicitly choose entities and notification actions. The connectivity sensor
is on when connected; problem sensors are on when a problem exists. Do not
interchange them. YAML syntax is tested; user-specific entity choices are not.

There is intentionally no unattended "retry/emergency feed" automation: a timeout
does not prove that food was not dispensed. Use the existing one-portion button
or the portions number control only after checking the feeder. The physical
button is independent. Command-register differences between models require
supervised verification before release.

The meal calendar currently displays schedules; it does not edit them. Use the
official HomeID app for schedule changes until write semantics and time zones
are verified. History-derived daily counters must not be presented as reliable
totals when the vendor returns only a partial history or omits portion counts.
