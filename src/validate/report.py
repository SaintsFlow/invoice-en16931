"""What a check says when it fails, and what the whole run says at the end.

A violation is written for a person who has to fix the invoice. It names the rule,
the business term, what was expected and what was actually there. "Does not add up"
is not an answer anyone can act on; "expected 1735.00, found 1200.00" is.
"""

from __future__ import annotations

from decimal import Decimal

from src.schema import StrictModel

# Rules that come from EN 16931 keep the code the standard gave them. Rules that are
# ours carry this prefix, so nobody has to wonder which document to look them up in.
OWN_PREFIX = "OWN-"


class Violation(StrictModel):
    """One thing that is wrong with an invoice."""

    rule: str
    """The rule that failed: BR-CO-14 from the standard, OWN-LINE-MATH from us."""

    bt: str | None
    """The business term the rule is about, when it is about a single one."""

    field: str
    """Where to look in the invoice, as a dotted path: totals.vat_total."""

    message: str
    """One sentence a person can act on."""

    expected: str | None = None
    actual: str | None = None

    @property
    def from_standard(self) -> bool:
        """Is this the standard talking, or us."""
        return not self.rule.startswith(OWN_PREFIX)


class ValidationReport(StrictModel):
    """The result of checking one invoice.

    The invoice itself is not in here. A failing invoice is handed on whole,
    alongside this, because somebody has to see what to correct.
    """

    valid: bool
    violations: list[Violation]

    @classmethod
    def of(cls, violations: list[Violation]) -> ValidationReport:
        return cls(valid=not violations, violations=violations)


def money(amount: Decimal) -> str:
    """How an amount is written in a violation: two decimals, always."""
    return f"{amount:.2f}"
