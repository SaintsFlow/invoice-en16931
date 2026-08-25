"""The extractor: what the model says is checked before it becomes an invoice.

Every test here runs on an answer a model produced, replayed from disk or built
from it. Nothing reaches the network, and the provider is scripted so a retry is
something a test can count rather than assume.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.errors import ExtractionFailedError
from src.extract.extractor import ATTEMPTS, PROMPT_PATH, InvoiceExtractor
from src.ocr.base import BoundingBox, OcrLine, OcrPage, OcrResult
from src.schema import PEPPOL_CUSTOMIZATION_ID, PEPPOL_PROFILE_ID, confidence_of
from tests.conftest import ScriptedProvider, recorded_answer


def ocr_of(*lines: str) -> OcrResult:
    """An OCR result carrying the given lines, and nothing else worth looking at."""
    read = [
        OcrLine(text=text, box=BoundingBox(left=0, top=0, width=100, height=14), confidence=90.0)
        for text in lines
    ]
    return OcrResult(engine="test", pages=[OcrPage(number=1, width=800, height=1000, lines=read)])


def answer_without(key: str) -> str:
    """The recorded answer with one field taken out, the way a model drops one."""
    payload = json.loads(recorded_answer())
    payload.pop(key)
    return json.dumps(payload)


async def test_a_recorded_answer_becomes_an_invoice() -> None:
    provider = ScriptedProvider(recorded_answer())

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung R-2026-0042"))

    assert invoice.number.value == "R-2026-0042"
    assert invoice.totals.gross_total.value == Decimal("240.00")
    assert isinstance(invoice.totals.gross_total.value, Decimal)
    assert provider.call_count == 1


async def test_money_sent_as_a_json_number_keeps_its_cents() -> None:
    """A JSON number is a float in Python, and a float cannot hold cents.

    The schema refuses floats in money on purpose, so an answer written with bare
    numbers would fail validation. Parsing with Decimal is what saves it.
    """
    payload = json.loads(recorded_answer())
    payload["totals"]["gross_total"]["value"] = 240.00
    payload["lines"][0]["net_price"]["value"] = 100.00
    provider = ScriptedProvider(json.dumps(payload))

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Gesamtbetrag 240,00"))

    assert invoice.totals.gross_total.value == Decimal("240.00")
    assert invoice.lines[0].net_price.value == Decimal("100.00")
    assert provider.call_count == 1


async def test_a_field_that_is_not_in_the_document_comes_back_empty() -> None:
    """The recorded answer leaves out two fields, each in the way models write it.

    `due_date` is a plain null, `buyer_reference` is the wrapper with nothing in
    it. Both mean the same thing, and both have to land as nothing at all.
    """
    provider = ScriptedProvider(recorded_answer())

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    assert invoice.due_date is None
    assert invoice.buyer_reference is None
    assert confidence_of(invoice.due_date) == 0.0
    assert confidence_of(invoice.buyer_reference) == 0.0
    # A field that was read still reports what it is worth.
    assert confidence_of(invoice.number) == pytest.approx(0.98)


@pytest.mark.parametrize("written", ["null", "NULL", " null ", "none", ""])
async def test_the_word_null_is_not_a_value(written: str) -> None:
    """qwen3:8b answered a missing field with the text "null", not with null.

    A string sails through validation, so without this the invoice would carry the
    word null where a human would read a buyer reference.
    """
    payload = json.loads(recorded_answer())
    payload["buyer_reference"] = {"value": written, "confidence": 0.4}
    provider = ScriptedProvider(json.dumps(payload))

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    assert invoice.buyer_reference is None


async def test_the_profile_identifiers_are_ours_not_the_models() -> None:
    """The recorded answer invents both. They are not printed on any invoice."""
    provider = ScriptedProvider(recorded_answer())

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    assert invoice.customization_id == PEPPOL_CUSTOMIZATION_ID
    assert invoice.profile_id == PEPPOL_PROFILE_ID


async def test_a_bad_answer_costs_one_retry_and_then_works() -> None:
    provider = ScriptedProvider(answer_without("number"), recorded_answer())

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung R-2026-0042"))

    assert invoice.number.value == "R-2026-0042"
    assert provider.call_count == 2
    complaint = provider.last_user_text()
    assert "number (BT-1)" in complaint
    assert "Field required" in complaint


async def test_prose_instead_of_json_is_also_worth_a_retry() -> None:
    provider = ScriptedProvider("I am sorry, I could not read this invoice.", recorded_answer())

    invoice = await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    assert invoice.number.value == "R-2026-0042"
    assert provider.call_count == 2


async def test_two_bad_answers_end_in_a_readable_error() -> None:
    provider = ScriptedProvider(answer_without("number"), answer_without("number"))

    with pytest.raises(ExtractionFailedError) as refused:
        await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    assert provider.call_count == ATTEMPTS
    assert refused.value.status_code == 422
    assert refused.value.code == "extraction_failed"
    # The BT code is what somebody checking against the standard looks up.
    assert any("number (BT-1)" in problem for problem in refused.value.problems)


async def test_long_text_is_cut_to_the_ceiling() -> None:
    provider = ScriptedProvider(recorded_answer())
    long_page = ocr_of(*[f"line {number} of a very long scan" for number in range(500)])

    await InvoiceExtractor(provider, max_ocr_chars=50).extract(long_page)

    sent = provider.calls[0][-1].content
    assert len(sent) == 50
    assert sent.startswith("line 0")


async def test_the_prompt_travels_with_the_request_and_forbids_guessing() -> None:
    """The prompt lives in a file, and the rule against guessing is the point of it."""
    provider = ScriptedProvider(recorded_answer())

    await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    system = provider.calls[0][0]
    assert system.role == "system"
    assert system.content == PROMPT_PATH.read_text(encoding="utf-8")
    assert "return null" in system.content
    assert "Never guess" in system.content


async def test_the_invoice_schema_goes_out_with_the_request() -> None:
    provider = ScriptedProvider(recorded_answer())

    await InvoiceExtractor(provider).extract(ocr_of("Rechnung"))

    schema = provider.schemas[0]
    assert "number" in schema["properties"]
    assert "vat_breakdown" in schema["properties"]


async def test_a_missing_prompt_file_is_not_silently_ignored(tmp_path: Path) -> None:
    """A prompt that is not there would otherwise become an empty system message."""
    provider = ScriptedProvider(recorded_answer())
    extractor = InvoiceExtractor(provider, prompt_path=tmp_path / "nowhere.md")

    with pytest.raises(FileNotFoundError):
        await extractor.extract(ocr_of("Rechnung"))
