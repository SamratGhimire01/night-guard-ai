"""Turns an adapter's free-text send result into the persisted `Message.delivery_status`."""

from app.services.conversation.style_checks import split_into_bubbles

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


def send_in_bubbles(text: str, send, *, channel: str) -> str:
    """Delivery-time bubble split shared by WhatsApp/Messenger/Instagram: sends `text` (the one, already-validated
    reply _handle_turn produced; the persisted Message row keeps it whole) as 1-3 messages via `split_into_bubbles`,
    stopping at the first bubble that fails (the rest would arrive out of order anyway). `send(bubble)` is one
    adapter send returning the usual detail string.

    Worst-of-N status collapse into ONE detail string, so `status_from_detail` above stays unchanged:
      - any real failure -> prefix "failed:" -- even if earlier bubbles sent, the customer didn't get the full reply.
      - no token configured -> every bubble is "simulated..." (they share one token) -> prefix "simulated".
      - every bubble sent for real -> prefix "sent", detail lists every message id.
    Voice never calls this."""
    bubbles = split_into_bubbles(text)
    results: list[str] = []
    for bubble in bubbles:
        results.append(send(bubble))
        if results[-1].startswith("failed"):
            break
    if len(results) == 1:
        return results[0]
    if results[-1].startswith("failed"):
        return f"failed: bubble {len(results)}/{len(bubbles)} of split reply failed ({results[-1]})"
    if all(d.startswith("simulated") for d in results):
        return f"simulated — no real {channel} access token configured ({len(results)} bubbles)"
    return "sent " + ", ".join(results)
