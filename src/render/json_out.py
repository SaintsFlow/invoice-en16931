"""A flat JSON view of an invoice, for anything that does not speak XML.

Flat means one level of keys, with the nesting spelled out in the names:
`seller_vat_id`, `totals_gross`. Lines and the VAT breakdown stay as lists, because
flattening those would mean inventing `line_1_name`, and nobody can loop over that.

Every key carries the BT code of the term it holds, in a companion map, so a reader
can check a field against the standard without opening this file. Money is a string
here for the same reason it is a Decimal everywhere else: a JSON number would lose
cents on the way through somebody else's parser.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from src.schema import Field, Invoice, confidence_of

CENTS: Final = Decimal("0.01")

# What each flat key means in EN 16931. Shipped with the document, so the receiving
# side does not have to guess or ask.
BT_CODES: Final[dict[str, str]] = {
    "number": "BT-1",
    "issue_date": "BT-2",
    "type_code": "BT-3",
    "currency": "BT-5",
    "due_date": "BT-9",
    "buyer_reference": "BT-10",
    "seller_name": "BT-27",
    "seller_vat_id": "BT-31",
    "seller_country": "BT-40",
    "buyer_name": "BT-44",
    "buyer_vat_id": "BT-48",
    "buyer_country": "BT-55",
    "totals_line_net": "BT-106",
    "totals_net": "BT-109",
    "totals_vat": "BT-110",
    "totals_gross": "BT-112",
    "totals_due": "BT-115",
}


def render(invoice: Invoice) -> dict[str, Any]:
    """Turn an invoice into the flat structure. Ready for json.dumps as it is."""
    totals = invoice.totals
    flat: dict[str, Any] = {
        "customization_id": invoice.customization_id,
        "profile_id": invoice.profile_id,
        "number": _text(invoice.number),
        "issue_date": invoice.issue_date.value.isoformat(),
        "type_code": _text(invoice.type_code),
        "currency": _text(invoice.currency),
        "due_date": invoice.due_date.value.isoformat() if invoice.due_date else None,
        "buyer_reference": _text(invoice.buyer_reference),
        "seller_name": _text(invoice.seller.name),
        "seller_vat_id": _text(invoice.seller.vat_id),
        "seller_country": _text(invoice.seller.address.country_code),
        "seller_city": _text(invoice.seller.address.city),
        "buyer_name": _text(invoice.buyer.name),
        "buyer_vat_id": _text(invoice.buyer.vat_id),
        "buyer_country": _text(invoice.buyer.address.country_code),
        "buyer_city": _text(invoice.buyer.address.city),
        "totals_line_net": _money(totals.line_net_total),
        "totals_net": _money(totals.net_total),
        "totals_vat": _money(totals.vat_total),
        "totals_gross": _money(totals.gross_total),
        "totals_due": _money(totals.amount_due),
        "lines": [
            {
                "number": index,
                "identifier": _text(line.identifier),
                "name": _text(line.name),
                "quantity": _plain(line.quantity),
                "unit": _text(line.quantity_unit_code),
                "net_price": _money(line.net_price),
                "net_amount": _money(line.net_amount),
                "vat_category": _text(line.vat_category_code),
                "vat_rate": _plain(line.vat_rate),
            }
            for index, line in enumerate(invoice.lines, start=1)
        ],
        "vat_breakdown": [
            {
                "category": _text(entry.category_code),
                "rate": _plain(entry.rate),
                "taxable_amount": _money(entry.taxable_amount),
                "tax_amount": _money(entry.tax_amount),
            }
            for entry in invoice.vat_breakdown
        ],
        "confidence": _confidence(invoice),
        "bt_codes": BT_CODES,
    }
    return flat


def _text(field: Field[Any] | None) -> str | None:
    return None if field is None else str(field.value)


def _money(field: Field[Any] | None) -> str | None:
    """Two decimals, as a string. A JSON number would lose the cents."""
    if field is None:
        return None
    value = field.value
    return f"{value.quantize(CENTS)}" if isinstance(value, Decimal) else str(value)


def _plain(field: Field[Any] | None) -> str | None:
    """A quantity or a rate: a string, but keeping the precision it was read with."""
    if field is None:
        return None
    value = field.value
    return format(value.normalize(), "f") if isinstance(value, Decimal) else str(value)


def _confidence(invoice: Invoice) -> dict[str, float]:
    """How sure we were about the fields a person is most likely to check.

    A field nobody could read counts as zero, which is the same answer
    confidence_of gives everywhere else.
    """
    return {
        "number": confidence_of(invoice.number),
        "issue_date": confidence_of(invoice.issue_date),
        "due_date": confidence_of(invoice.due_date),
        "currency": confidence_of(invoice.currency),
        "seller_name": confidence_of(invoice.seller.name),
        "buyer_name": confidence_of(invoice.buyer.name),
        "totals_gross": confidence_of(invoice.totals.gross_total),
    }
