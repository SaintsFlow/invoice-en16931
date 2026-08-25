"""Helpers shared by the tests."""

from __future__ import annotations

from pathlib import Path

from src.ocr.base import BoundingBox, OcrEngine, OcrLine, OcrPage, OcrResult

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
