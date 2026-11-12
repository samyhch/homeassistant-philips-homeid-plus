# Supervised feeder verification

This checklist is for a person next to the feeder. It is not an automation.
Do not run a physical check during a scheduled meal, with another integration
sending commands, or if extra food could be a problem. If possible, collect
and count the test food separately.

For each model (PAW3320/02 and PAW5320/02), record firmware, integration version,
and whether the controls were available before the test. Start by reading
device status and checking the schedule; do not change the schedule.

1. Press the Home Assistant **one-portion** control once. Record both the
   software outcome and the amount physically dispensed.
2. Only after accounting for that food, use **Dispense portions now** with two
   portions once, if the additional food is safe. Record the same observations.
3. Compare with the HomeID history after it updates. A log entry is useful
   evidence, but not a substitute for checking the food in the tray.
4. If the result is ambiguous, times out, or permission is denied, stop.
   Inspect the feeder and its history before deciding whether to try again.
   Do not automatically repeat the action or try a different transport.

Do not infer the N-portions register from the one-portion action or the
physical button. This branch changes neither register nor the schedule API.
Record observed counts, not credentials, device IDs or camera URLs.
