"""The UNOPTIMIZED baseline responder -- deliberately a plain, generic DSPy
program with a minimal instruction (NOT the production system prompt). This is
the thing a later phase will optimize; here it just proves the loop works.

It is business-agnostic: the only business-specific input is the facts text
rendered by lab.businesses (all fictional -- no real customer, appointment, or
business data is ever read or written by the lab)."""
import dspy

from lab.businesses import facts_text


class Reply(dspy.Signature):
    """You are a friendly receptionist chatbot for a small business. Reply to the customer's latest message."""

    business_facts: str = dspy.InputField()
    conversation_so_far: str = dspy.InputField(desc="earlier turns, oldest first")
    customer_message: str = dspy.InputField()
    response: str = dspy.OutputField(desc="the reply to send to the customer")


class BaselineReceptionist(dspy.Module):
    def __init__(self, business: str = "dental"):
        super().__init__()
        self.business = business
        self.reply = dspy.Predict(Reply)

    def forward(self, customer_message: str, history: list[tuple[str, str]] | None = None, *, lm=None):
        convo = "\n".join(f"{who}: {text}" for who, text in (history or [])) or "(start of conversation)"
        return self.reply(business_facts=facts_text(self.business), conversation_so_far=convo,
                          customer_message=customer_message, lm=lm)
