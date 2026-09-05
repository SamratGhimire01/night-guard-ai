"""Shared string constraints for client-writable text fields.

Phase 29 finding (real, live-verified — see
tests/security/test_phase29_input_validation.py): several schemas had bare
`str` fields with no length cap while their DB columns are bounded
(`String(255)` etc). A 200,000-char name reached the DB as an unhandled
`StringDataRightTruncation`, and a name containing an embedded NUL byte
reached psycopg2 as an unhandled `ValueError: A string literal cannot
contain NUL (0x00) characters.` — both surfaced as raw 500s instead of a
clean 422. `safe_str(max_length)` closes both for any field that uses it:
the max_length must match (or be safely under) the field's real DB column
width, chosen per call site rather than one shared constant, since those
widths genuinely differ (phone vs. name vs. address)."""

from typing import Annotated

from pydantic import StringConstraints
from pydantic.functional_validators import AfterValidator


def _reject_nul_bytes(value: str) -> str:
    if "\x00" in value:
        raise ValueError("This field must not contain NUL characters.")
    return value


def safe_str(max_length: int):
    return Annotated[str, StringConstraints(max_length=max_length), AfterValidator(_reject_nul_bytes)]
