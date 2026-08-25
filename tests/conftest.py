"""Helpers shared by the tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from src.ocr.base import BoundingBox, OcrEngine, OcrLine, OcrPage, OcrResult
from src.schema import (
    CountryCode,
    CurrencyCode,
    Field,
    Invoice,
    InvoiceLine,
    Money,
    Party,
    PostalAddress,
    Totals,
    VatBreakdown,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

# Enough of a PDF for the signature check, and never sent to a real engine.
MINIMAL_PDF = b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


class CountingEngine(OcrEngine):
    """Stands in for a real engine and counts how often it had to read.

    Tests that are not about tesseract itself use this: it answers in
    milliseconds and it makes a second read visible.
    """

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    async def read(self, pdf: bytes) -> OcrResult:
        self.calls += 1
        line = OcrLine(
            text="Rechnungsnummer: 2026-0042",
            box=BoundingBox(left=10, top=10, width=200, height=14),
            confidence=95.0,
        )
        page = OcrPage(number=1, width=2480, height=3508, lines=[line])
        return OcrResult(engine=self.name, pages=[page])


def sample_invoice() -> Invoice:
    """One complete invoice that adds up: 2 x 100.00 EUR, 20 percent VAT, 240.00 due.

    Tests that need a broken invoice start from this one and take a piece away,
    so what the test is about stays visible in the test itself.
    """
    return Invoice(
        number=Field[str](value="R-2026-0042", confidence=0.98),
        issue_date=Field[date](value=date(2026, 8, 25)),
        currency=Field[CurrencyCode](value="EUR"),
        due_date=Field[date](value=date(2026, 9, 24), confidence=0.8),
        seller=Party(
            name=Field[str](value="Muster Handel GmbH"),
            vat_id=Field[str](value="ATU12345678", confidence=0.91),
            address=PostalAddress(
                line_one=Field[str](value="Hauptstrasse 1"),
                city=Field[str](value="Wien"),
                post_code=Field[str](value="1010"),
                country_code=Field[CountryCode](value="AT"),
            ),
        ),
        buyer=Party(
            name=Field[str](value="Beispiel Kunde AG"),
            address=PostalAddress(
                city=Field[str](value="Muenchen"),
                post_code=Field[str](value="80331"),
                country_code=Field[CountryCode](value="DE"),
            ),
        ),
        lines=[
            InvoiceLine(
                name=Field[str](value="Beratung"),
                quantity=Field[Money](value=Decimal("2")),
                quantity_unit_code=Field[str](value="HUR"),
                net_price=Field[Money](value=Decimal("100.00")),
                net_amount=Field[Money](value=Decimal("200.00")),
                vat_category_code=Field[str](value="S"),
                vat_rate=Field[Money](value=Decimal("20")),
            )
        ],
        vat_breakdown=[
            VatBreakdown(
                category_code=Field[str](value="S"),
                rate=Field[Money](value=Decimal("20")),
                taxable_amount=Field[Money](value=Decimal("200.00")),
                tax_amount=Field[Money](value=Decimal("40.00")),
            )
        ],
        totals=Totals(
            line_net_total=Field[Money](value=Decimal("200.00")),
            net_total=Field[Money](value=Decimal("200.00")),
            vat_total=Field[Money](value=Decimal("40.00")),
            gross_total=Field[Money](value=Decimal("240.00")),
            amount_due=Field[Money](value=Decimal("240.00")),
        ),
    )
