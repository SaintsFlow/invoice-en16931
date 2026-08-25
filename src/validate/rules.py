"""The checks an invoice has to pass. One function per rule, so one test per rule.

Rule codes are not invented here. Everything named BR-something is quoted from the
Schematron the European Commission publishes for EN 16931, and the docstring carries
the wording of the rule itself. Rules that are ours, because the standard has no
check for them, carry the OWN- prefix and say so.

Two things are deliberately not checked here:

* Rules the model in src/schema.py already makes impossible. An invoice with no
  number cannot be built at all, so BR-02 can only ever catch a blank one, and
  BR-16 (at least one line) cannot fail. Writing code for a case that cannot
  happen only makes the next reader wonder what they are missing. The list is at
  the bottom of this docstring.
* Anything about allowances and charges. The model has no BT-107 or BT-108 yet, so
  BR-CO-13 reduces to "the total without VAT is the sum of the lines", which is
  what it does below.

Already impossible, so not coded: BR-03 and BR-05 (an issue date and a currency are
required and typed), BR-09 and BR-11 (both country codes are required two-letter
strings), BR-12 and BR-14 (both totals are required amounts), BR-16 (the model
demands at least one line).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from src.schema import Field, Invoice
from src.validate.currencies import CURRENCIES
from src.validate.report import ValidationReport, Violation, money

# A cent of rounding is how real invoices are written and is not an error. Two cents
# is somebody's arithmetic going wrong. The number is here, alone, because it is the
# kind of thing that gets argued about.
TOLERANCE: Final = Decimal("0.01")

CENTS: Final = Decimal("0.01")

# VAT identifiers whose shape we actually know. Everything else is only checked for
# the country prefix the standard asks for, which is better than pretending to know.
# Two prefixes are not country codes on purpose: Greece invoices as EL, and Northern
# Ireland as XI.
VAT_SHAPES: Final = {
    "AT": re.compile(r"^ATU[0-9]{8}$"),
    "DE": re.compile(r"^DE[0-9]{9}$"),
}
VAT_PREFIX: Final = re.compile(r"^[A-Z]{2}")

Rule = Callable[[Invoice], list[Violation]]


def _empty(field: Field[Any] | None) -> bool:
    """Nobody filled this in, or filled it with blank space."""
    if field is None:
        return True
    return isinstance(field.value, str) and not field.value.strip()


def _missing(
    field: Field[Any] | None, rule: str, bt: str, where: str, what: str
) -> list[Violation]:
    if not _empty(field):
        return []
    return [
        Violation(
            rule=rule,
            bt=bt,
            field=where,
            message=f"the invoice must carry {what}",
            expected="a value",
            actual="nothing",
        )
    ]


def _agrees(
    actual: Decimal, expected: Decimal, rule: str, bt: str, where: str, what: str
) -> list[Violation]:
    """Compare two amounts and say how far apart they are when they disagree."""
    gap = abs(actual - expected)
    if gap <= TOLERANCE:
        return []
    return [
        Violation(
            rule=rule,
            bt=bt,
            field=where,
            message=f"{where} is off from {what} by {money(gap)}",
            expected=money(expected),
            actual=money(actual),
        )
    ]


def _rounded(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def _line_net_sum(invoice: Invoice) -> Decimal | None:
    """The sum of the line net amounts, or None when a line has not got one.

    None rather than a guess: BR-24 already reports the missing amount, and adding
    up what is left would produce a second, misleading violation.
    """
    total = Decimal("0")
    for line in invoice.lines:
        if line.net_amount is None:
            return None
        total += line.net_amount.value
    return total


# --- fields that have to be there -------------------------------------------------


def br_02_invoice_number(invoice: Invoice) -> list[Violation]:
    """BR-02: An Invoice shall have an Invoice number (BT-1)."""
    return _missing(invoice.number, "BR-02", "BT-1", "number", "an invoice number")


def br_04_invoice_type_code(invoice: Invoice) -> list[Violation]:
    """BR-04: An Invoice shall have an Invoice type code (BT-3)."""
    return _missing(
        invoice.type_code, "BR-04", "BT-3", "type_code", "an invoice type code, 380 for an invoice"
    )


def br_06_seller_name(invoice: Invoice) -> list[Violation]:
    """BR-06: An Invoice shall contain the Seller name (BT-27)."""
    return _missing(invoice.seller.name, "BR-06", "BT-27", "seller.name", "the seller name")


def br_07_buyer_name(invoice: Invoice) -> list[Violation]:
    """BR-07: An Invoice shall contain the Buyer name (BT-44)."""
    return _missing(invoice.buyer.name, "BR-07", "BT-44", "buyer.name", "the buyer name")


def br_13_net_total(invoice: Invoice) -> list[Violation]:
    """BR-13: An Invoice shall have the Invoice total amount without VAT (BT-109)."""
    return _missing(
        invoice.totals.net_total,
        "BR-13",
        "BT-109",
        "totals.net_total",
        "the total amount without VAT",
    )


def br_15_amount_due(invoice: Invoice) -> list[Violation]:
    """BR-15: An Invoice shall have the Amount due for payment (BT-115)."""
    return _missing(
        invoice.totals.amount_due, "BR-15", "BT-115", "totals.amount_due", "the amount due"
    )


def br_23_quantity_unit(invoice: Invoice) -> list[Violation]:
    """BR-23: An Invoice line shall have an Invoiced quantity unit of measure code."""
    found: list[Violation] = []
    for index, line in enumerate(invoice.lines):
        found += _missing(
            line.quantity_unit_code,
            "BR-23",
            "BT-130",
            f"lines[{index}].quantity_unit_code",
            "a unit of measure on every line, HUR for an hour, C62 for a piece",
        )
    return found


def br_24_line_net_amount(invoice: Invoice) -> list[Violation]:
    """BR-24: Each Invoice line shall have an Invoice line net amount (BT-131)."""
    found: list[Violation] = []
    for index, line in enumerate(invoice.lines):
        found += _missing(
            line.net_amount,
            "BR-24",
            "BT-131",
            f"lines[{index}].net_amount",
            "a net amount on every line",
        )
    return found


def br_62_seller_endpoint_scheme(invoice: Invoice) -> list[Violation]:
    """BR-62: The Seller electronic address (BT-34) shall have a Scheme identifier."""
    if invoice.seller.endpoint_id is None:
        return []
    return _missing(
        invoice.seller.endpoint_scheme_id,
        "BR-62",
        "BT-34-1",
        "seller.endpoint_scheme_id",
        "a scheme for the seller electronic address, 9915 for an Austrian VAT number",
    )


def br_63_buyer_endpoint_scheme(invoice: Invoice) -> list[Violation]:
    """BR-63: The Buyer electronic address (BT-49) shall have a Scheme identifier."""
    if invoice.buyer.endpoint_id is None:
        return []
    return _missing(
        invoice.buyer.endpoint_scheme_id,
        "BR-63",
        "BT-49-1",
        "buyer.endpoint_scheme_id",
        "a scheme for the buyer electronic address",
    )


# --- the arithmetic ---------------------------------------------------------------


def br_co_10_line_total(invoice: Invoice) -> list[Violation]:
    """BR-CO-10: Sum of Invoice line net amount (BT-106) = sum of BT-131."""
    total = _line_net_sum(invoice)
    if total is None:
        return []
    return _agrees(
        invoice.totals.line_net_total.value,
        total,
        "BR-CO-10",
        "BT-106",
        "totals.line_net_total",
        "the sum of the line net amounts",
    )


def br_co_13_net_total(invoice: Invoice) -> list[Violation]:
    """BR-CO-13: Invoice total amount without VAT (BT-109) = sum of BT-131.

    The standard also subtracts document allowances and adds document charges. The
    model carries neither yet, so what is left is the sum of the lines.
    """
    total = _line_net_sum(invoice)
    if total is None or invoice.totals.net_total is None:
        return []
    return _agrees(
        invoice.totals.net_total.value,
        total,
        "BR-CO-13",
        "BT-109",
        "totals.net_total",
        "the sum of the line net amounts",
    )


def br_co_14_vat_total(invoice: Invoice) -> list[Violation]:
    """BR-CO-14: Invoice total VAT amount (BT-110) = sum of VAT category tax amounts."""
    charged = sum((entry.tax_amount.value for entry in invoice.vat_breakdown), Decimal("0"))
    return _agrees(
        invoice.totals.vat_total.value,
        charged,
        "BR-CO-14",
        "BT-110",
        "totals.vat_total",
        "the VAT of the breakdown added up",
    )


def br_co_15_gross_total(invoice: Invoice) -> list[Violation]:
    """BR-CO-15: Total with VAT (BT-112) = total without VAT (BT-109) + VAT (BT-110)."""
    if invoice.totals.net_total is None:
        return []
    expected = invoice.totals.net_total.value + invoice.totals.vat_total.value
    return _agrees(
        invoice.totals.gross_total.value,
        expected,
        "BR-CO-15",
        "BT-112",
        "totals.gross_total",
        "the total without VAT plus the VAT",
    )


def br_co_16_amount_due(invoice: Invoice) -> list[Violation]:
    """BR-CO-16: Amount due (BT-115) = total with VAT (BT-112) - paid + rounding.

    Nothing paid and nothing rounded is carried in the model, so the amount due is
    the total with VAT.
    """
    if invoice.totals.amount_due is None:
        return []
    return _agrees(
        invoice.totals.amount_due.value,
        invoice.totals.gross_total.value,
        "BR-CO-16",
        "BT-115",
        "totals.amount_due",
        "the total with VAT",
    )


def br_co_17_vat_per_rate(invoice: Invoice) -> list[Violation]:
    """BR-CO-17: VAT category tax amount = taxable amount x rate / 100, two decimals."""
    found: list[Violation] = []
    for index, entry in enumerate(invoice.vat_breakdown):
        expected = _rounded(entry.taxable_amount.value * entry.rate.value / Decimal("100"))
        found += _agrees(
            entry.tax_amount.value,
            expected,
            "BR-CO-17",
            "BT-117",
            f"vat_breakdown[{index}].tax_amount",
            f"{money(entry.taxable_amount.value)} at {entry.rate.value}%",
        )
    return found


# --- ours, because the standard has no check for it -------------------------------


def own_line_math(invoice: Invoice) -> list[Violation]:
    """OWN-LINE-MATH: line net amount (BT-131) = quantity (BT-129) x price (BT-146).

    EN 16931 defines this as a calculation but does not check it: the Schematron
    only demands that BT-131 is present and that the lines add up to BT-106. A model
    that reads a price and a quantity off a page and then invents the line total is
    exactly what this project has to catch, so the check is ours.
    """
    found: list[Violation] = []
    for index, line in enumerate(invoice.lines):
        if line.net_amount is None:
            continue
        expected = _rounded(line.quantity.value * line.net_price.value)
        found += _agrees(
            line.net_amount.value,
            expected,
            "OWN-LINE-MATH",
            "BT-131",
            f"lines[{index}].net_amount",
            f"{line.quantity.value} at {money(line.net_price.value)}",
        )
    return found


def own_vat_base(invoice: Invoice) -> list[Violation]:
    """OWN-VAT-BASE: a taxable amount equals the lines charged at that rate.

    The standard says this once per VAT category, in BR-S-08 for standard rated,
    BR-Z-08 for zero rated and so on down the list. Those need a reliable category
    code, and the models tested so far put the rate in that field instead. Matching
    on the rate works today and catches the error that actually turned up: a
    breakdown that claimed a base of 1200.00 while charging VAT on 1700.00.
    """
    priced: dict[Decimal, Decimal] = {}
    for line in invoice.lines:
        if line.net_amount is None or line.vat_rate is None:
            return []
        rate = line.vat_rate.value
        priced[rate] = priced.get(rate, Decimal("0")) + line.net_amount.value

    found: list[Violation] = []
    for index, entry in enumerate(invoice.vat_breakdown):
        charged = priced.get(entry.rate.value)
        if charged is None:
            continue
        found += _agrees(
            entry.taxable_amount.value,
            charged,
            "OWN-VAT-BASE",
            "BT-116",
            f"vat_breakdown[{index}].taxable_amount",
            f"the lines charged at {entry.rate.value}%",
        )
    return found


def own_due_after_issue(invoice: Invoice) -> list[Violation]:
    """OWN-DUE-AFTER-ISSUE: the payment due date is not before the issue date.

    Not a rule of EN 16931, which happily accepts an invoice due before it was
    written. It is still always a reading error or a typo. Same day is fine: cash
    on delivery is a real arrangement.
    """
    if invoice.due_date is None:
        return []
    due: date = invoice.due_date.value
    issued: date = invoice.issue_date.value
    if due >= issued:
        return []
    return [
        Violation(
            rule="OWN-DUE-AFTER-ISSUE",
            bt="BT-9",
            field="due_date",
            message="the invoice is due before it was issued",
            expected=f"on or after {issued.isoformat()}",
            actual=due.isoformat(),
        )
    ]


def own_currency_known(invoice: Invoice) -> list[Violation]:
    """OWN-CURRENCY-KNOWN: the currency is a code from ISO 4217.

    BR-05 only asks that a currency is there. Whether it is a real one is checked
    against the published list in src/validate/currencies.py.
    """
    code = invoice.currency.value
    if code in CURRENCIES:
        return []
    return [
        Violation(
            rule="OWN-CURRENCY-KNOWN",
            bt="BT-5",
            field="currency",
            message=f"{code} is not a currency an invoice can be written in",
            expected="a code from ISO 4217",
            actual=code,
        )
    ]


def br_co_09_vat_identifiers(invoice: Invoice) -> list[Violation]:
    """BR-CO-09: a VAT identifier shall have a country prefix from ISO 3166-1.

    Where the shape of a country's VAT number is known, that is checked too. Where
    it is not, the prefix is all that can honestly be said.
    """
    found: list[Violation] = []
    for role, party in (("seller", invoice.seller), ("buyer", invoice.buyer)):
        if party.vat_id is None:
            continue
        given = party.vat_id.value.strip().upper()
        bt = "BT-31" if role == "seller" else "BT-48"
        where = f"{role}.vat_id"

        if not VAT_PREFIX.match(given):
            found.append(
                Violation(
                    rule="BR-CO-09",
                    bt=bt,
                    field=where,
                    message="a VAT identifier starts with the two letter country code",
                    expected="two letters, then the number",
                    actual=given,
                )
            )
            continue

        shape = VAT_SHAPES.get(given[:2])
        if shape is not None and not shape.match(given):
            found.append(
                Violation(
                    rule="BR-CO-09",
                    bt=bt,
                    field=where,
                    message=f"this is not the shape of a {given[:2]} VAT identifier",
                    expected=shape.pattern,
                    actual=given,
                )
            )
    return found


RULES: Final[tuple[Rule, ...]] = (
    br_02_invoice_number,
    br_04_invoice_type_code,
    br_06_seller_name,
    br_07_buyer_name,
    br_13_net_total,
    br_15_amount_due,
    br_23_quantity_unit,
    br_24_line_net_amount,
    br_62_seller_endpoint_scheme,
    br_63_buyer_endpoint_scheme,
    br_co_09_vat_identifiers,
    br_co_10_line_total,
    br_co_13_net_total,
    br_co_14_vat_total,
    br_co_15_gross_total,
    br_co_16_amount_due,
    br_co_17_vat_per_rate,
    own_line_math,
    own_vat_base,
    own_due_after_issue,
    own_currency_known,
)


def check(invoice: Invoice) -> ValidationReport:
    """Run every rule and collect what is wrong.

    All rules run, always. Stopping at the first problem would send somebody back
    and forth over the same invoice one correction at a time.
    """
    found: list[Violation] = []
    for rule in RULES:
        found += rule(invoice)
    return ValidationReport.of(found)
