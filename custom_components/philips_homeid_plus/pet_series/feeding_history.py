"""Count observed feedings, never infer portions or complete vendor history."""
from datetime import datetime


def observed_feedings_today(events, device_id, now):
    """Deduplicate identified events in the caller's local day.

    Missing device IDs, ambiguous naive dates and future events are excluded.
    meal_amount has no verified unit, so it is deliberately not summed as portions.
    """
    seen = set()
    for event in events:
        if str(getattr(event, "device_id", "")) != str(device_id):
            continue
        identity = getattr(event, "id", None)
        if not identity:
            continue
        try:
            time = datetime.fromisoformat(str(event.time).replace("Z", "+00:00"))
            if time.tzinfo is None or now.tzinfo is None:
                continue
            if time <= now and time.astimezone(now.tzinfo).date() == now.date():
                seen.add(str(identity))
        except (ValueError, TypeError, AttributeError):
            continue
    return len(seen)
