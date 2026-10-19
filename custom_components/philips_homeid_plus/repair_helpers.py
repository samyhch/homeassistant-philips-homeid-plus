"""Actionable setup problems reported through Home Assistant Repairs."""

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


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
