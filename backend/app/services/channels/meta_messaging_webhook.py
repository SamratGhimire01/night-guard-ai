def extract_incoming_text_messages(payload: dict) -> list[dict]:
    """Walks the real `entry[].messaging[]` webhook envelope shape — and this
    is a genuine, byte-for-byte structural match, not just "similar enough to
    force together": Meta's Messenger Platform and Instagram Messaging
    webhooks are both built on the same underlying messaging-webhook
    infrastructure (Instagram DMs were brought onto the Messenger Platform's
    own conversations model), so both deliver `entry[].id` (the receiving
    account — a Facebook Page id for Messenger, an Instagram-scoped business
    account id for Instagram) and `entry[].messaging[]` events shaped
    identically: `sender.id` / `recipient.id` / `message.mid` / `message.text`
    / `message.is_echo`. Only the *meaning* of the ids differs (PSID vs
    IGSID) — the JSON shape and field names do not. That's what justifies one
    real shared parser here instead of two near-identical copies (Phase 27's
    explicit ask); WhatsApp Cloud API's `entry[].changes[].value.messages[]`
    shape is genuinely different and deliberately NOT folded into this
    function (see whatsapp_webhook.py's own extract_incoming_text_messages).

    Returns one normalized dict per real incoming TEXT message:
    {account_id, sender_id, message_id, text} — generic names on purpose,
    since this function itself has no concept of "Page" vs "Instagram
    account"; each channel's own webhook module maps these onto its own
    channel-specific vocabulary (page_id/psid for Messenger, ig_account_id/
    igsid for Instagram) when resolving the tenant and building the reply.

    Deliberately tolerant, not a strict schema: this identical endpoint shape
    also delivers delivery/read receipts (no `message` key), postbacks
    (button taps, no `message.text`), and echoes of the account's OWN
    outgoing sends (`message.is_echo: true`) — all silently skipped, never a
    crash, since raising here would make Meta retry-storm us over events we
    don't act on.
    """
    results = []
    for entry in payload.get("entry", []) or []:
        account_id = entry.get("id")
        for event in entry.get("messaging", []) or []:
            message = event.get("message") or {}
            if not message or message.get("is_echo"):
                continue
            text = message.get("text")
            sender_id = (event.get("sender") or {}).get("id")
            message_id = message.get("mid")
            if not (account_id and sender_id and message_id and text):
                continue
            results.append({"account_id": account_id, "sender_id": sender_id, "message_id": message_id, "text": text})
    return results


# Attachment `type` -> what staff see. Messenger and Instagram share these; anything not listed gets the generic line.
_ATTACHMENT_PLACEHOLDERS = {
    "image": "[Customer sent an image]",
    "audio": "[Customer sent a voice note]",
    "video": "[Customer sent a video]",
    "file": "[Customer sent a document]",
    "location": "[Customer shared a location]",
    "share": "[Customer shared a post]",
    "story_mention": "[Customer mentioned your story]",
}
_GENERIC_PLACEHOLDER = "[Customer sent a message this channel can't show]"


def extract_incoming_non_text_messages(payload: dict) -> list[dict]:
    """The attachment-only counterpart of `extract_incoming_text_messages`: one dict per real incoming message that has NO
    text but at least one attachment: {account_id, sender_id, message_id, placeholder}. Echoes of our own sends, receipts and
    postbacks are still skipped. (A message with text AND an attachment is handled by the text path: the text is kept and the
    attachment is not recorded — a known v1 limit.)"""
    results = []
    for entry in payload.get("entry", []) or []:
        account_id = entry.get("id")
        for event in entry.get("messaging", []) or []:
            message = event.get("message") or {}
            if not message or message.get("is_echo") or message.get("text"):
                continue
            attachments = message.get("attachments") or []
            sender_id = (event.get("sender") or {}).get("id")
            message_id = message.get("mid")
            if not (attachments and account_id and sender_id and message_id):
                continue
            kind = (attachments[0] or {}).get("type")
            results.append(
                {
                    "account_id": account_id,
                    "sender_id": sender_id,
                    "message_id": message_id,
                    "placeholder": _ATTACHMENT_PLACEHOLDERS.get(kind, _GENERIC_PLACEHOLDER),
                }
            )
    return results
