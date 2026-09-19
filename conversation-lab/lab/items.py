"""One conversation turn to respond to, shared by the seed set, the eval set and every arm (so all arms see identical input)."""
from dataclasses import dataclass, field

from lab.businesses import facts_text


@dataclass
class Item:
    id: str
    biz: str                       # key in lab.businesses.BUSINESSES
    customer: str
    history: list = field(default_factory=list)   # [(who, text)], who in {"Customer","Assistant"}
    note: str = ""                 # situational fact the real system would have (booking draft, slots shown...)
    gold: str | None = None        # a real, recorded GOOD reply, when one exists (labeled demo material)
    prov: str = ""

    def facts(self) -> str:
        return facts_text(self.biz, sandbox_note=False) + (f"\nSituation notes: {self.note}" if self.note else "")

    def convo(self) -> str:
        return "\n".join(f"{w}: {t}" for w, t in self.history)
