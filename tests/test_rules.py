"""One test per rule: a good invoice says nothing, a broken one says exactly one thing.

Every test starts from the same complete invoice and breaks one thing in it. That
keeps what the test is about visible in the test, and it means a rule that fires on
an invoice it has no business with shows up immediately, as a second violation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.schema import CurrencyCode, Field, Invoice, Money
from src.validate.rules import RULES, TOLERANCE, check
from tests.conftest import sample_invoice


def broken(**changes: object) -> Invoice:
    """The sample invoice with something changed, straight from its own JSON.

    Going through the model rather than mutating the object keeps the result a
    real invoice, one that a caller could have sent us.
    """
    payload = sample_invoice().model_dump()
    payload.update(changes)
    return Invoice.model_validate(payload)


def codes(invoice: Invoice) -> list[str]:
    return [violation.rule for violation in check(invoice).violations]


def only(invoice: Invoice, rule: str) -> None:
    """The invoice breaks this rule and nothing else."""
    assert codes(invoice) == [rule]


def test_a_complete_invoice_passes_every_rule() -> None:
    report = check(sample_invoice())

    assert report.valid
    assert report.violations == []


def test_every_rule_is_registered_once() -> None:
    """A rule that is written but never registered is a rule that does not run."""
    names = [rule.__name__ for rule in RULES]

    assert len(names) == len(set(names))
    assert len(names) == 21


# --- fields that have to be there -------------------------------------------------


def test_br_02_catches_a_blank_invoice_number() -> None:
    only(broken(number={"value": "   ", "confidence": 1.0}), "BR-02")


def test_br_04_catches_a_missing_type_code() -> None:
    only(broken(type_code=None), "BR-04")


def test_br_06_catches_a_blank_seller_name() -> None:
    invoice = sample_invoice().model_dump()
    invoice["seller"]["name"] = {"value": "", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-06")


def test_br_07_catches_a_blank_buyer_name() -> None:
    invoice = sample_invoice().model_dump()
    invoice["buyer"]["name"] = {"value": "", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-07")


def test_br_13_catches_a_missing_total_without_vat() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["net_total"] = None
    only(Invoice.model_validate(invoice), "BR-13")


def test_br_15_catches_a_missing_amount_due() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["amount_due"] = None
    only(Invoice.model_validate(invoice), "BR-15")


def test_br_23_catches_a_line_without_a_unit() -> None:
    invoice = sample_invoice().model_dump()
    invoice["lines"][0]["quantity_unit_code"] = None
    only(Invoice.model_validate(invoice), "BR-23")


def test_br_24_catches_a_line_without_a_net_amount() -> None:
    """The amount is missing, so the sums that need it stay quiet on purpose."""
    invoice = sample_invoice().model_dump()
    invoice["lines"][0]["net_amount"] = None

    assert codes(Invoice.model_validate(invoice)) == ["BR-24"]


def test_br_62_catches_a_seller_address_without_a_scheme() -> None:
    invoice = sample_invoice().model_dump()
    invoice["seller"]["endpoint_id"] = {"value": "ATU12345678", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-62")


def test_br_62_stays_quiet_when_there_is_no_electronic_address() -> None:
    """The rule is about an address that exists, not about having one."""
    assert check(sample_invoice()).valid


def test_br_63_catches_a_buyer_address_without_a_scheme() -> None:
    invoice = sample_invoice().model_dump()
    invoice["buyer"]["endpoint_id"] = {"value": "9930:DE123456789", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-63")


# --- the arithmetic ---------------------------------------------------------------


def test_br_co_10_catches_lines_that_do_not_add_up_to_the_line_total() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["line_net_total"] = {"value": Decimal("150.00"), "confidence": 1.0}
    reported = check(Invoice.model_validate(invoice)).violations

    # Only this one: BR-CO-13 and BR-CO-15 are about BT-109, which is untouched here.
    assert [v.rule for v in reported] == ["BR-CO-10"]
    gap = next(v for v in reported if v.rule == "BR-CO-10")
    assert gap.expected == "200.00"
    assert gap.actual == "150.00"
    assert "50.00" in gap.message


def test_br_co_13_catches_a_wrong_total_without_vat() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["net_total"] = {"value": Decimal("190.00"), "confidence": 1.0}

    assert codes(Invoice.model_validate(invoice)) == ["BR-CO-13", "BR-CO-15"]


def test_br_co_14_catches_a_vat_total_that_is_not_the_breakdown() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["vat_total"] = {"value": Decimal("35.00"), "confidence": 1.0}

    assert codes(Invoice.model_validate(invoice)) == ["BR-CO-14", "BR-CO-15"]


def test_br_co_15_catches_a_gross_that_is_not_net_plus_vat() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["gross_total"] = {"value": Decimal("999.00"), "confidence": 1.0}

    assert codes(Invoice.model_validate(invoice)) == ["BR-CO-15", "BR-CO-16"]


def test_br_co_16_catches_an_amount_due_that_is_not_the_gross() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["amount_due"] = {"value": Decimal("100.00"), "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-CO-16")


def test_br_co_17_catches_vat_that_is_not_the_rate_of_the_base() -> None:
    invoice = sample_invoice().model_dump()
    invoice["vat_breakdown"][0]["tax_amount"] = {"value": Decimal("30.00"), "confidence": 1.0}
    reported = check(Invoice.model_validate(invoice)).violations

    assert [v.rule for v in reported] == ["BR-CO-14", "BR-CO-17"]
    per_rate = next(v for v in reported if v.rule == "BR-CO-17")
    assert per_rate.expected == "40.00"
    assert "200.00 at 20%" in per_rate.message


# --- ours -------------------------------------------------------------------------


def test_own_line_math_catches_a_line_total_that_is_not_quantity_times_price() -> None:
    """The line claims a total nobody could have got from its own numbers."""
    invoice = sample_invoice().model_dump()
    invoice["lines"][0]["net_amount"] = {"value": Decimal("250.00"), "confidence": 1.0}
    reported = check(Invoice.model_validate(invoice)).violations

    assert "OWN-LINE-MATH" in [v.rule for v in reported]
    math = next(v for v in reported if v.rule == "OWN-LINE-MATH")
    assert math.expected == "200.00"
    assert math.actual == "250.00"


def test_own_vat_base_catches_a_base_that_is_not_the_lines_at_that_rate() -> None:
    """The error a live model actually made: right VAT, wrong base."""
    invoice = sample_invoice().model_dump()
    invoice["vat_breakdown"][0]["taxable_amount"] = {"value": Decimal("120.00"), "confidence": 1.0}
    reported = check(Invoice.model_validate(invoice)).violations

    assert "OWN-VAT-BASE" in [v.rule for v in reported]
    base = next(v for v in reported if v.rule == "OWN-VAT-BASE")
    assert base.expected == "200.00"
    assert base.actual == "120.00"
    assert "the lines charged at 20%" in base.message


def test_own_due_after_issue_catches_a_due_date_before_the_issue_date() -> None:
    only(broken(due_date={"value": date(2026, 8, 24), "confidence": 1.0}), "OWN-DUE-AFTER-ISSUE")


def test_the_same_day_is_a_fine_due_date() -> None:
    """Cash on delivery is a real arrangement, not a reading error."""
    assert check(broken(due_date={"value": date(2026, 8, 25), "confidence": 1.0})).valid


def test_own_currency_known_catches_something_that_is_not_a_currency() -> None:
    only(broken(currency={"value": "XXX", "confidence": 1.0}), "OWN-CURRENCY-KNOWN")


def test_a_real_currency_passes() -> None:
    assert check(broken(currency={"value": "CHF", "confidence": 1.0})).valid


def test_br_co_09_catches_a_vat_identifier_without_a_country() -> None:
    invoice = sample_invoice().model_dump()
    invoice["seller"]["vat_id"] = {"value": "12345678", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-CO-09")


def test_br_co_09_catches_an_austrian_number_of_the_wrong_shape() -> None:
    invoice = sample_invoice().model_dump()
    invoice["seller"]["vat_id"] = {"value": "ATU1234", "confidence": 1.0}
    only(Invoice.model_validate(invoice), "BR-CO-09")


def test_br_co_09_leaves_a_country_it_does_not_know_alone() -> None:
    """Only the prefix can honestly be checked for a country whose shape we lack."""
    invoice = sample_invoice().model_dump()
    invoice["seller"]["vat_id"] = {"value": "SI12345678", "confidence": 1.0}

    assert check(Invoice.model_validate(invoice)).valid


# --- the rounding threshold -------------------------------------------------------


@pytest.mark.parametrize(
    ("off_by", "expected_codes"),
    [
        (Decimal("0.01"), []),
        (Decimal("-0.01"), []),
        (Decimal("0.02"), ["BR-CO-16"]),
        (Decimal("-0.02"), ["BR-CO-16"]),
    ],
)
def test_a_cent_is_rounding_and_two_cents_is_an_error(
    off_by: Decimal, expected_codes: list[str]
) -> None:
    invoice = sample_invoice().model_dump()
    due = invoice["totals"]["amount_due"]["value"] + off_by
    invoice["totals"]["amount_due"] = {"value": due, "confidence": 1.0}

    assert codes(Invoice.model_validate(invoice)) == expected_codes


def test_the_threshold_is_one_cent_and_says_so() -> None:
    assert str(TOLERANCE) == "0.01"


# --- what the report is for -------------------------------------------------------


def test_a_broken_invoice_still_comes_back_whole() -> None:
    """Nothing is thrown away. A person has to see what to correct."""
    invoice = broken(currency=Field[CurrencyCode](value="XXX").model_dump())
    report = check(invoice)

    assert not report.valid
    assert invoice.number.value == "R-2026-0042"
    assert invoice.totals.gross_total.value == Decimal("240.00")


def test_a_violation_says_which_book_the_rule_is_from() -> None:
    standard = check(broken(type_code=None)).violations[0]
    ours = check(broken(currency=Field[CurrencyCode](value="XXX").model_dump())).violations[0]

    assert standard.from_standard
    assert not ours.from_standard


def test_money_in_a_violation_always_carries_two_decimals() -> None:
    invoice = sample_invoice().model_dump()
    invoice["totals"]["amount_due"] = {"value": Decimal("240.5"), "confidence": 1.0}
    reported = check(Invoice.model_validate(invoice)).violations[0]

    assert reported.actual == "240.50"
    assert reported.expected == "240.00"


def test_money_is_still_never_a_float() -> None:
    """A violation carries text, so no amount can pick up a float on the way out."""
    invoice = sample_invoice().model_dump()
    invoice["lines"][0]["net_price"] = {"value": Money("33.33"), "confidence": 1.0}
    for violation in check(Invoice.model_validate(invoice)).violations:
        assert isinstance(violation.expected, str | type(None))
        assert isinstance(violation.actual, str | type(None))
