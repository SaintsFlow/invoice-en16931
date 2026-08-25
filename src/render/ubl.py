"""Building the UBL 2.1 Invoice XML that Peppol carries.

Two things about UBL trip people up and both are handled here rather than left to
whoever reads the output.

Element order is part of the schema. UBL declares sequences, not free bags of
elements, so CityName after PostalZone is not a style preference, it is invalid XML
that a receiver will reject. The order used below was read out of
schemas/ubl-2.1 rather than remembered, and tests/test_ubl.py validates against
those same schemas, so a wrong order fails the gate instead of failing at a customer.

An amount without a currency is not an amount. Every monetary element carries
currencyID, and the value is written from the Decimal, so cents survive the trip.

What is not built here: allowances, charges, payment means, delivery, order
references, attachments. The model has none of them yet. When it grows one, the
element goes in at the position the schema gives it, not at the end.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final
from xml.etree import ElementTree as ET

from src.schema import Field, Invoice, InvoiceLine, Money, Party, PostalAddress, VatBreakdown

UBL: Final = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

# UBL keeps VAT under a named tax scheme. Everything this service handles is VAT.
VAT_SCHEME: Final = "VAT"

# Amounts go out with two decimals. UBL allows more, EN 16931 does not (BR-DEC-*),
# and an invoice written to three decimals is an invoice somebody has to argue about.
CENTS: Final = Decimal("0.01")


def render(invoice: Invoice) -> str:
    """Turn an invoice into UBL 2.1 XML, as a string with an XML declaration."""
    ET.register_namespace("", UBL)
    ET.register_namespace("cac", CAC)
    ET.register_namespace("cbc", CBC)

    root = ET.Element(f"{{{UBL}}}Invoice")
    currency = invoice.currency.value

    _basic(root, "CustomizationID", invoice.customization_id)
    _basic(root, "ProfileID", invoice.profile_id)
    _basic(root, "ID", invoice.number.value)
    _basic(root, "IssueDate", invoice.issue_date.value.isoformat())
    if invoice.due_date is not None:
        _basic(root, "DueDate", invoice.due_date.value.isoformat())
    if invoice.type_code is not None:
        _basic(root, "InvoiceTypeCode", invoice.type_code.value)
    _basic(root, "DocumentCurrencyCode", currency)
    if invoice.buyer_reference is not None:
        _basic(root, "BuyerReference", invoice.buyer_reference.value)

    _party(root, "AccountingSupplierParty", invoice.seller)
    _party(root, "AccountingCustomerParty", invoice.buyer)
    _tax_total(root, invoice, currency)
    _totals(root, invoice, currency)

    for number, line in enumerate(invoice.lines, start=1):
        _line(root, number, line, currency)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _basic(parent: ET.Element, name: str, text: str, **attributes: str) -> ET.Element:
    """One cbc element, the leaf kind that carries a value."""
    element = ET.SubElement(parent, f"{{{CBC}}}{name}", attributes)
    element.text = text
    return element


def _group(parent: ET.Element, name: str) -> ET.Element:
    """One cac element, the kind that holds other elements."""
    return ET.SubElement(parent, f"{{{CAC}}}{name}")


def _amount(parent: ET.Element, name: str, value: Decimal, currency: str) -> None:
    """A monetary amount. Never without its currency."""
    _basic(parent, name, _money(value), currencyID=currency)


def _money(value: Decimal) -> str:
    return f"{value.quantize(CENTS)}"


def _quantity(value: Decimal) -> str:
    """A quantity keeps whatever precision it was read with, unlike money."""
    return format(value.normalize(), "f")


def _party(root: ET.Element, wrapper: str, party: Party) -> None:
    holder = _group(root, wrapper)
    element = _group(holder, "Party")

    if party.endpoint_id is not None:
        attributes = {}
        if party.endpoint_scheme_id is not None:
            attributes["schemeID"] = party.endpoint_scheme_id.value
        _basic(element, "EndpointID", party.endpoint_id.value, **attributes)

    name = _group(element, "PartyName")
    _basic(name, "Name", party.name.value)

    _address(element, party.address)

    if party.vat_id is not None:
        scheme = _group(element, "PartyTaxScheme")
        _basic(scheme, "CompanyID", party.vat_id.value)
        _basic(_group(scheme, "TaxScheme"), "ID", VAT_SCHEME)

    legal = _group(element, "PartyLegalEntity")
    _basic(legal, "RegistrationName", party.name.value)


def _address(parent: ET.Element, address: PostalAddress) -> None:
    element = _group(parent, "PostalAddress")
    _optional(element, "StreetName", address.line_one)
    _optional(element, "AdditionalStreetName", address.line_two)
    _optional(element, "CityName", address.city)
    _optional(element, "PostalZone", address.post_code)
    _optional(element, "CountrySubentity", address.country_subdivision)
    _basic(_group(element, "Country"), "IdentificationCode", address.country_code.value)


def _optional(parent: ET.Element, name: str, field: Field[str] | None) -> None:
    """Leave the element out when nobody could read the value.

    An empty element would say "this address has no city", which is a different
    claim from "the scan did not show one".
    """
    if field is not None and field.value.strip():
        _basic(parent, name, field.value)


def _tax_total(root: ET.Element, invoice: Invoice, currency: str) -> None:
    total = _group(root, "TaxTotal")
    _amount(total, "TaxAmount", invoice.totals.vat_total.value, currency)
    for entry in invoice.vat_breakdown:
        _tax_subtotal(total, entry, currency)


def _tax_subtotal(parent: ET.Element, entry: VatBreakdown, currency: str) -> None:
    subtotal = _group(parent, "TaxSubtotal")
    _amount(subtotal, "TaxableAmount", entry.taxable_amount.value, currency)
    _amount(subtotal, "TaxAmount", entry.tax_amount.value, currency)
    _tax_category(subtotal, entry.category_code.value, entry.rate.value)


def _tax_category(parent: ET.Element, code: str, rate: Decimal, name: str = "TaxCategory") -> None:
    """The same shape under two names: TaxCategory in a breakdown, ClassifiedTaxCategory
    on a line. UBL calls them differently and the schema will not accept a swap."""
    category = _group(parent, name)
    _basic(category, "ID", code)
    _basic(category, "Percent", _quantity(rate))
    _basic(_group(category, "TaxScheme"), "ID", VAT_SCHEME)


def _totals(root: ET.Element, invoice: Invoice, currency: str) -> None:
    totals = invoice.totals
    element = _group(root, "LegalMonetaryTotal")
    _amount(element, "LineExtensionAmount", totals.line_net_total.value, currency)
    # The total without VAT falls back to the line total, which is what it equals
    # while the model carries no document allowances or charges.
    without_vat = totals.net_total.value if totals.net_total else totals.line_net_total.value
    _amount(element, "TaxExclusiveAmount", without_vat, currency)
    _amount(element, "TaxInclusiveAmount", totals.gross_total.value, currency)
    due = totals.amount_due.value if totals.amount_due else totals.gross_total.value
    _amount(element, "PayableAmount", due, currency)


def _line(root: ET.Element, number: int, line: InvoiceLine, currency: str) -> None:
    element = _group(root, "InvoiceLine")
    _basic(element, "ID", line.identifier.value if line.identifier else str(number))

    unit = line.quantity_unit_code.value if line.quantity_unit_code else _UNIT_UNKNOWN
    _basic(element, "InvoicedQuantity", _quantity(line.quantity.value), unitCode=unit)

    net = line.net_amount.value if line.net_amount else _line_net(line)
    _amount(element, "LineExtensionAmount", net, currency)

    item = _group(element, "Item")
    _basic(item, "Name", line.name.value)
    _tax_category_of_line(item, line)

    price = _group(element, "Price")
    _amount(price, "PriceAmount", line.net_price.value, currency)


# UN/ECE Recommendation 20 for "one piece". Used only when the invoice did not print
# a unit at all: the schema demands an attribute, and BR-23 has already reported the
# gap, so this fills the hole without hiding it.
_UNIT_UNKNOWN: Final = "C62"


def _line_net(line: InvoiceLine) -> Money:
    """What the line comes to, when the invoice did not say."""
    return (line.quantity.value * line.net_price.value).quantize(CENTS)


def _tax_category_of_line(item: ET.Element, line: InvoiceLine) -> None:
    rate = line.vat_rate.value if line.vat_rate else Decimal("0")
    _tax_category(item, line.vat_category_code.value, rate, name="ClassifiedTaxCategory")
