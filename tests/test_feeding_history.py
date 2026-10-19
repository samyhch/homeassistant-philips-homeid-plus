"""Day boundaries and duplicate/misassigned events must not inflate feeding counts."""
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/philips_homeid_plus/pet_series/feeding_history.py"
spec = importlib.util.spec_from_file_location("feeding_history_test", path)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


class FeedingHistoryTests(unittest.TestCase):
    def test_local_day_deduplication_and_device_filter(self):
        now = datetime(2026, 10, 19, 12, tzinfo=timezone(timedelta(hours=3)))
        def event(identity, time, device="fixture"):
            return SimpleNamespace(id=identity, time=time, device_id=device)
        events = [event("one", "2026-10-18T22:00:00Z"), event("one", "2026-10-18T22:00:00Z"),
                  event("yesterday", "2026-10-18T20:00:00Z"), event("other", "2026-10-19T08:00:00Z", "other"),
                  event("ambiguous", "2026-10-19T08:00:00Z", None), event("future", "2026-10-20T00:00:00Z"),
                  event("bad", "invalid"), event("naive", "2026-10-19T08:00:00")]
        self.assertEqual(history.observed_feedings_today(events, "fixture", now), 1)

    def test_empty_history_is_zero_observed_events_not_proof_of_no_food(self):
        self.assertEqual(history.observed_feedings_today([], "fixture", datetime.now(timezone.utc)), 0)
