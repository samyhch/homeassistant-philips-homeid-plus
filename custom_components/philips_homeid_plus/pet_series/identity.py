"""Non-destructive migration of the legacy one-portion button's unique ID."""


def stable_device_identity(unique_ids, backend_id, vendor_id, linked_ids=()):
    """Reuse the identity already owning entities, including an older CPP ID.

    Discovery links the current backend ID to a Tuya vendor ID. HA's device
    registry can also link that vendor ID to the previous backend identity.
    Never rewrite entity IDs or assume every existing user used Tuya IDs.
    """
    backend_id = str(backend_id)
    vendor_id = str(vendor_id) if vendor_id else backend_id
    candidates = list(dict.fromkeys([vendor_id, backend_id, *map(str, linked_ids)]))
    scores = {
        candidate: sum(
            unique_id.startswith(candidate + "_")
            and unique_id != candidate + "_dispense_one_portion"
            for unique_id in unique_ids
        )
        for candidate in candidates
    }
    selected = max(candidates, key=scores.get)
    return selected if scores[selected] else vendor_id


def migrate_feed_button_identity(registry, domain, target, device_id):
    """Keep entity_id/history; never delete or overwrite an existing identity."""
    if not target or not device_id:
        return
    old_id = registry.async_get_entity_id("button", domain, f"{target}_dispense_one_portion")
    new_unique = f"{device_id}_feed_button"
    if old_id and not registry.async_get_entity_id("button", domain, new_unique):
        registry.async_update_entity(old_id, new_unique_id=new_unique)
