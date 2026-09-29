from app.db.models.business import Business
from app.db.models.conversation import Message
from app.db.models.customer import Customer
from app.services.notifications.templates.render import render_followup_email

_QUOTE_MAX_LENGTH = 200


def compose_followup_email(*, business: Business, customer: Customer, interest_message: Message) -> tuple[str, str, str]:
    """Deterministic subject/plain-text/HTML — no LLM involvement, same
    discipline as app.services.notifications.content.compose_email. The
    "real thing they asked about" is the customer's own real message content,
    quoted verbatim (truncated if long) — not an LLM's re-interpretation of
    it, and not a fabricated summary of what service they might have meant."""
    subject = f"Still interested in {business.name}?"
    quoted = interest_message.content.strip()
    if len(quoted) > _QUOTE_MAX_LENGTH:
        quoted = quoted[: _QUOTE_MAX_LENGTH - 3] + "..."

    greeting = f"Hi {customer.known_name}," if customer.known_name else "Hi,"
    body = (
        f"{greeting}\n\n"
        f"We wanted to follow up — you recently asked us:\n\n"
        f'"{quoted}"\n\n'
        f"If you'd still like to book, or have any other questions, just reply to this "
        f"email or reach out to {business.name} directly and we'll be happy to help.\n"
    )

    html_body = render_followup_email(
        business_name=business.name,
        business_address=business.address,
        business_phone=business.phone,
        business_email=business.email,
        customer_name=customer.known_name,
        quoted_message=quoted,
    )
    return subject, body, html_body
