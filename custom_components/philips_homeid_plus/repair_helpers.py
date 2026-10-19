"""Actionable setup problems reported through Home Assistant Repairs."""

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

SETUP_ISSUES = ("auth_expired", "local_unreachable", "integration_conflict", "missing_credentials")


def report_setup_issue(hass, entry, key):
    """Create one stable, entry-scoped warning without credential placeholders."""
    if key not in SETUP_ISSUES:
        raise ValueError("Unknown setup issue")
    ir.async_create_issue(hass, DOMAIN, f"{key}_{entry.entry_id}", is_fixable=False,
                         severity=ir.IssueSeverity.ERROR, translation_key=key,
                         translation_placeholders={"entry": entry.title})


def clear_setup_issues(hass, entry, *, keep_conflict=False):
    for key in SETUP_ISSUES:
        if key == "integration_conflict" and keep_conflict:
            continue
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry.entry_id}")


def has_active_conflict(entry, entries):
    """Only warn about exact identities/hosts on an actively loaded old backend."""
    for other in entries:
        if other.domain not in {"philips_airpurifier_coap", "philips_pet_series", "philips_homeid"}:
            continue
        if getattr(other, "disabled_by", None) is not None:
            continue
        state = getattr(other, "state", None)
        if getattr(state, "value", state) not in {"loaded", "setup_in_progress"}:
            continue
        for key in ("device_id", "tuya_device_id", "host"):
            value = entry.options.get(key, entry.data.get(key))
            other_value = other.options.get(key, other.data.get(key))
            if value and value == other_value:
                return True
    return False


def report_missing_pet_devices(hass, entry) -> None:
    """Report a saved feeder which is absent from HomeID discovery."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"missing_pet_devices_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="missing_pet_devices",
        translation_placeholders={"entry": entry.title},
        learn_more_url=(
            "https://github.com/samyhch/homeassistant-philips-homeid-plus"
            "/blob/main/docs/TROUBLESHOOTING.md#no-matching-pet-devices"
        ),
    )


def clear_missing_pet_devices(hass, entry) -> None:
    """Remove the issue when setup succeeds or the entry is removed."""
    ir.async_delete_issue(hass, DOMAIN, f"missing_pet_devices_{entry.entry_id}")
