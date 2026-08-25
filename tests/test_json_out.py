"""The flat JSON, and whether it says the same thing as the XML.

Two renderings of one invoice that disagree are worse than one rendering, because
whichever the receiver reads, somebody downstream has the other number.
"""

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from src.render import json_out
from src.render.ubl import CAC, CBC
from src.render.ubl import render as render_xml
from src.schema import Invoice
from tests.conftest import sample_invoice


def xml_text(root: ET.Element, path: str) -> str | None:
    found = root.find(path, {"cac": CAC, "cbc": CBC})
    return None if found is None else found.text


def test_the_flat_json_carries_the_fields_a_person_looks_for() -> None:
    flat = json_out.render(sample_invoice())

    assert flat["number"] == "R-2026-0042"
    assert flat["issue_date"] == "2026-08-25"
    assert flat["currency"] == "EUR"
    assert flat["seller_name"] == "Muster Handel GmbH"
    assert flat["seller_vat_id"] == "ATU12345678"
    assert flat["buyer_country"] == "DE"
    assert flat["totals_gross"] == "240.00"
    assert len(flat["lines"]) == 1
    assert len(flat["vat_breakdown"]) == 1


def test_xml_and_json_say_the_same_thing() -> None:
    """Paired on purpose. Checking each alone would let them drift apart."""
    invoice = sample_invoice()
    flat = json_out.render(invoice)
    root = ET.fromstring(render_xml(invoice))

    pairs = [
        (flat["number"], xml_text(root, "cbc:ID")),
        (flat["issue_date"], xml_text(root, "cbc:IssueDate")),
        (flat["currency"], xml_text(root, "cbc:DocumentCurrencyCode")),
        (
            flat["seller_name"],
            xml_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name"),
        ),
        (
            flat["buyer_name"],
            xml_text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name"),
        ),
        (flat["totals_line_net"], xml_text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount")),
        (flat["totals_net"], xml_text(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")),
        (flat["totals_vat"], xml_text(root, "cac:TaxTotal/cbc:TaxAmount")),
        (flat["totals_gross"], xml_text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")),
        (flat["totals_due"], xml_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")),
    ]
    for from_json, from_xml in pairs:
        assert from_json == from_xml

    assert len(flat["lines"]) == len(root.findall("cac:InvoiceLine", {"cac": CAC}))
    assert len(flat["vat_breakdown"]) == len(
        root.findall("cac:TaxTotal/cac:TaxSubtotal", {"cac": CAC})
    )


def test_money_is_a_string_with_two_decimals_and_never_a_number() -> None:
    """A JSON number loses cents in somebody else's parser, so none are written."""
    flat = json_out.render(sample_invoice())
    written = json.dumps(flat)

    for key in ("totals_line_net", "totals_net", "totals_vat", "totals_gross", "totals_due"):
        assert isinstance(flat[key], str)
        assert flat[key].count(".") == 1
        assert len(flat[key].split(".")[1]) == 2
    assert '"totals_gross": "240.00"' in written


def test_a_field_nobody_read_comes_back_as_null() -> None:
    payload = sample_invoice().model_dump()
    payload["seller"]["vat_id"] = None
    payload["due_date"] = None
    flat = json_out.render(Invoice.model_validate(payload))

    assert flat["seller_vat_id"] is None
    assert flat["due_date"] is None
    assert flat["confidence"]["due_date"] == 0.0


def test_the_bt_codes_travel_with_the_document() -> None:
    """The receiver should not have to ask what totals_gross means."""
    flat = json_out.render(sample_invoice())

    assert flat["bt_codes"]["totals_gross"] == "BT-112"
    assert flat["bt_codes"]["number"] == "BT-1"
    for key in flat["bt_codes"]:
        assert key in flat, f"{key} has a BT code but no field"


def test_the_whole_thing_survives_json_dumps() -> None:
    """Nothing in here is a Decimal or a date that json would refuse."""
    written = json.dumps(json_out.render(sample_invoice()), ensure_ascii=False)

    assert json.loads(written)["number"] == "R-2026-0042"
