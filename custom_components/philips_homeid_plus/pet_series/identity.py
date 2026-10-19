"""Non-destructive migration of the legacy one-portion button's unique ID."""


def migrate_feed_button_identity(registry, domain, target, device_id):
    """Keep entity_id/history; never delete or overwrite an existing identity."""
    if not target or not device_id:
        return
    old_id = registry.async_get_entity_id("button", domain, f"{target}_dispense_one_portion")
    new_unique = f"{device_id}_feed_button"
    if old_id and not registry.async_get_entity_id("button", domain, new_unique):
        registry.async_update_entity(old_id, new_unique_id=new_unique)
