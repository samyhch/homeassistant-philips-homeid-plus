"""Registry migration preserves entity IDs and respects conflicting identities."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

path = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/pet_series/identity.py"
spec = importlib.util.spec_from_file_location("identity_test", path)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class IdentityTests(unittest.TestCase):
    def test_only_unique_id_changes_not_entity_id(self):
        registry = SimpleNamespace(async_get_entity_id=Mock(side_effect=["button.existing", None]), async_update_entity=Mock())
        identity.migrate_feed_button_identity(registry, "fixture", "old", "new")
        registry.async_update_entity.assert_called_once_with("button.existing", new_unique_id="new_feed_button")

    def test_existing_target_and_missing_legacy_are_untouched(self):
        for lookups in (["button.old", "button.new"], [None]):
            registry = SimpleNamespace(async_get_entity_id=Mock(side_effect=lookups), async_update_entity=Mock())
            identity.migrate_feed_button_identity(registry, "fixture", "old", "new")
            registry.async_update_entity.assert_not_called()

    def test_no_identity_does_not_query_registry(self):
        registry = SimpleNamespace(async_get_entity_id=Mock(), async_update_entity=Mock())
        identity.migrate_feed_button_identity(registry, "fixture", None, "new")
        registry.async_get_entity_id.assert_not_called()
