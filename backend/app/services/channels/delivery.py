"""Turns an adapter's free-text send result into the persisted `Message.delivery_status`."""

SENT, SIMULATED, FAILED, SUPPRESSED, PENDING = "sent", "simulated", "failed", "suppressed", "pending"


def status_from_detail(detail: str) -> str:
    """The adapters (WhatsApp/Messenger/Instagram) never raise; they return "sent wamid=…" / "sent mid=…", "simulated — …"
    (no real token configured) or "failed: …". `proactive` adds "recorded; …" for a channel with nothing to push to (not
    connected / no identity / a push exception) — that is a failure from the customer's point of view. The widget's
    "recorded for widget poll" is a successful hand-off: the widget picks the message up on its next poll."""
    if detail.startswith("sent") or detail.startswith("recorded for widget poll"):
        return SENT
    if detail.startswith("simulated"):
        return SIMULATED
    return FAILED
