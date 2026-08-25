"""The UBL rendering, checked against the schemas OASIS publishes.

Validating against the real XSD is the whole point. XML that merely looks like UBL is
worth nothing: the receiver validates, and a document that fails there fails after it
has left, when nobody is watching.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
import xmlschema

from src.render.ubl import CAC, CBC, UBL, render
from src.schema import PEPPOL_CUSTOMIZATION_ID, PEPPOL_PROFILE_ID, Invoice
from tests.conftest import sample_invoice

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas/ubl-2.1/maindoc/UBL-Invoice-2.1.xsd"


@pytest.fixture(scope="module")
def ubl_schema() -> xmlschema.XMLSchema:
    """Loading the UBL tree takes a moment, so it is loaded once for the module."""
    return xmlschema.XMLSchema(str(SCHEMA_PATH))


def tree(invoice: Invoice) -> ET.Element:
    return ET.fromstring(render(invoice))


def text_at(root: ET.Element, path: str) -> str | None:
    found = root.find(path, {"cac": CAC, "cbc": CBC})
    return None if found is None else found.text


def test_the_rendered_invoice_validates_against_ubl_2_1(ubl_schema: xmlschema.XMLSchema) -> None:
    ubl_schema.validate(render(sample_invoice()))


def test_an_invoice_with_everything_filled_in_still_validates(
    ubl_schema: xmlschema.XMLSchema,
) -> None:
    """The optional elements have their own places in the sequence, so they get tested."""
    payload = sample_invoice().model_dump()
    payload["buyer_reference"] = {"value": "PO-2026-88", "confidence": 1.0}
    payload["seller"]["endpoint_id"] = {"value": "ATU12345678", "confidence": 1.0}
    payload["seller"]["endpoint_scheme_id"] = {"value": "9915", "confidence": 1.0}
    payload["buyer"]["endpoint_id"] = {"value": "9930:DE123456789", "confidence": 1.0}
    payload["buyer"]["endpoint_scheme_id"] = {"value": "0088", "confidence": 1.0}
    payload["seller"]["address"]["line_two"] = {"value": "Stiege 2", "confidence": 1.0}
    payload["seller"]["address"]["country_subdivision"] = {"value": "Wien", "confidence": 1.0}
    payload["lines"][0]["identifier"] = {"value": "POS-1", "confidence": 1.0}

    ubl_schema.validate(render(Invoice.model_validate(payload)))


def test_the_root_and_the_namespaces_are_ubl() -> None:
    root = tree(sample_invoice())

    assert root.tag == f"{{{UBL}}}Invoice"
    assert text_at(root, "cbc:CustomizationID") == PEPPOL_CUSTOMIZATION_ID
    assert text_at(root, "cbc:ProfileID") == PEPPOL_PROFILE_ID


def test_element_order_follows_the_schema(ubl_schema: xmlschema.XMLSchema) -> None:
    """UBL declares sequences, so a swap is invalid, not just untidy.

    The check runs against the schema rather than a list written here, because a
    list written here would be one more thing remembered instead of looked up.
    """
    root = tree(sample_invoice())
    address = root.find("cac:AccountingSupplierParty/cac:Party/cac:PostalAddress", {"cac": CAC})
    assert address is not None

    city = address.find("cbc:CityName", {"cbc": CBC})
    zone = address.find("cbc:PostalZone", {"cbc": CBC})
    assert list(address).index(city) < list(address).index(zone)  # type: ignore[arg-type]

    # And prove the schema is what enforces it: swap the two and validation fails.
    address.remove(city)  # type: ignore[arg-type]
    address.insert(list(address).index(zone) + 1, city)  # type: ignore[arg-type]
    with pytest.raises(xmlschema.XMLSchemaValidationError):
        ubl_schema.validate(ET.tostring(root, encoding="unicode"))


def test_every_amount_carries_its_currency() -> None:
    root = tree(sample_invoice())
    amounts = [
        element
        for element in root.iter()
        if element.tag.endswith("Amount") and element.tag.startswith(f"{{{CBC}}}")
    ]

    assert amounts, "no amounts found, this test is checking nothing"
    for element in amounts:
        assert element.get("currencyID") == "EUR", element.tag


def test_money_keeps_its_cents_and_two_decimals() -> None:
    root = tree(sample_invoice())

    assert text_at(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount") == "240.00"
    assert text_at(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount") == "200.00"
    assert text_at(root, "cac:TaxTotal/cbc:TaxAmount") == "40.00"


def test_a_line_carries_its_quantity_unit_and_price() -> None:
    root = tree(sample_invoice())
    line = root.find("cac:InvoiceLine", {"cac": CAC})
    assert line is not None

    quantity = line.find("cbc:InvoicedQuantity", {"cbc": CBC})
    assert quantity is not None
    assert quantity.text == "2"
    assert quantity.get("unitCode") == "HUR"
    assert text_at(line, "cbc:LineExtensionAmount") == "200.00"
    assert text_at(line, "cac:Item/cbc:Name") == "Beratung"
    assert text_at(line, "cac:Price/cbc:PriceAmount") == "100.00"


def test_a_line_without_a_unit_still_validates(ubl_schema: xmlschema.XMLSchema) -> None:
    """The schema demands unitCode. BR-23 has already reported the gap."""
    payload = sample_invoice().model_dump()
    payload["lines"][0]["quantity_unit_code"] = None
    xml = render(Invoice.model_validate(payload))

    ubl_schema.validate(xml)
    assert 'unitCode="C62"' in xml


def test_the_vat_breakdown_becomes_a_tax_subtotal() -> None:
    root = tree(sample_invoice())
    subtotal = root.find("cac:TaxTotal/cac:TaxSubtotal", {"cac": CAC})
    assert subtotal is not None

    assert text_at(subtotal, "cbc:TaxableAmount") == "200.00"
    assert text_at(subtotal, "cbc:TaxAmount") == "40.00"
    assert text_at(subtotal, "cac:TaxCategory/cbc:ID") == "S"
    assert text_at(subtotal, "cac:TaxCategory/cbc:Percent") == "20"
    assert text_at(subtotal, "cac:TaxCategory/cac:TaxScheme/cbc:ID") == "VAT"


def test_a_field_nobody_could_read_is_left_out_entirely() -> None:
    """An empty element claims the invoice has no city. A missing one claims nothing."""
    payload = sample_invoice().model_dump()
    payload["seller"]["address"]["city"] = None
    root = tree(Invoice.model_validate(payload))

    assert (
        text_at(root, "cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CityName")
        is None
    )


def test_an_electronic_address_carries_its_scheme() -> None:
    payload = sample_invoice().model_dump()
    payload["seller"]["endpoint_id"] = {"value": "ATU12345678", "confidence": 1.0}
    payload["seller"]["endpoint_scheme_id"] = {"value": "9915", "confidence": 1.0}
    root = tree(Invoice.model_validate(payload))

    endpoint = root.find(
        "cac:AccountingSupplierParty/cac:Party/cbc:EndpointID", {"cac": CAC, "cbc": CBC}
    )
    assert endpoint is not None
    assert endpoint.text == "ATU12345678"
    assert endpoint.get("schemeID") == "9915"


def test_the_declaration_is_there_so_a_receiver_knows_the_encoding() -> None:
    xml = render(sample_invoice())

    assert xml.startswith("<?xml version=")
    assert "utf-8" in xml[:60].lower()


def test_a_rate_with_trailing_zeros_is_written_plainly() -> None:
    """20.00 percent is 20 percent, and a receiver should not have to wonder."""
    payload: dict[str, Any] = sample_invoice().model_dump()
    payload["vat_breakdown"][0]["rate"] = {"value": Decimal("20.00"), "confidence": 1.0}
    root = tree(Invoice.model_validate(payload))

    assert text_at(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent") == "20"
