"""Reads the generated sample invoice with the tesseract shipped in the image."""

from __future__ import annotations

import pytest

from src.ocr.tesseract import TesseractEngine
from tests.conftest import SAMPLES

INVOICE = SAMPLES / "invoice-01.pdf"


@pytest.fixture
def sample_pdf() -> bytes:
    if not INVOICE.exists():
        pytest.fail(f"{INVOICE} is missing, run python3 scripts/make_samples.py")
    return INVOICE.read_bytes()


async def test_invoice_number_and_total_are_read(sample_pdf: bytes) -> None:
    result = await TesseractEngine().read(sample_pdf)

    assert result.engine == "tesseract"
    assert len(result.pages) == 1
    assert "2026-0042" in result.text
    assert "2078,50" in result.text


async def test_table_rows_come_back_as_separate_lines(sample_pdf: bytes) -> None:
    """The whole point of keeping layout: one invoice line is one text line."""
    page = (await TesseractEngine().read(sample_pdf)).pages[0]

    beratung = [line for line in page.lines if "Beratung" in line.text]
    lizenz = [line for line in page.lines if "Lizenz" in line.text]

    assert len(beratung) == 1
    assert len(lizenz) == 1
    # Each row carries its own amount, instead of the amounts pooling somewhere.
    assert "1200,00" in beratung[0].text
    assert "500,00" in lizenz[0].text
    # Two rows, two places on the page.
    assert beratung[0].box.top < lizenz[0].box.top


async def test_lines_have_boxes_and_confidence(sample_pdf: bytes) -> None:
    page = (await TesseractEngine().read(sample_pdf)).pages[0]

    assert page.width > 0
    assert page.height > 0
    for line in page.lines:
        assert line.box.width > 0
        assert line.box.height > 0
        assert 0.0 <= line.confidence <= 100.0
