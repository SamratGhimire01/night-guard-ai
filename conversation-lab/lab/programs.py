"""The DSPy reply programs + the judge-based metric shared by the optimizer and the eval script."""
import dspy

from lab.businesses import BUSINESSES
from lab.judge import ReplyJudge
from lab.production_prompt import RULES_INSTRUCTION

SIG = dspy.Signature("business_name, business_facts, conversation_so_far, customer_message -> response", RULES_INSTRUCTION)


class RulesReceptionist(dspy.Module):
    """Starting point for optimization: the production reply-style rules as a plain instruction, no demos."""
    def __init__(self):
        super().__init__()
        self.reply = dspy.Predict(SIG)

    def forward(self, business_name, business_facts, conversation_so_far, customer_message):
        return self.reply(business_name=business_name, business_facts=business_facts, conversation_so_far=conversation_so_far,
                          customer_message=customer_message)


def to_example(it) -> dspy.Example:
    return dspy.Example(business_name=BUSINESSES[it.biz]["name"], business_facts=it.facts(),
                        conversation_so_far=it.convo() or "(start of conversation)", customer_message=it.customer
                        ).with_inputs("business_name", "business_facts", "conversation_so_far", "customer_message")


def make_metric(samples: int = 3):
    """Judge score / 100, default reasoning effort (the calibrated judge). Same judge the validation sets validate."""
    judge = ReplyJudge(samples=samples)

    def metric(example, pred, trace=None, pred_name=None, pred_trace=None):
        conv = example.conversation_so_far
        return judge(example.customer_message, pred.response, conversation="" if conv.startswith("(start") else conv,
                     facts=example.business_facts).score / 100

    return metric
