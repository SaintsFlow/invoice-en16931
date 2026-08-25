"""API tests: the upload is checked, then read by whichever engine is set up."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import MAX_UPLOAD_BYTES, app, lifespan
from src.errors import UnknownOcrEngineError
from src.extract.extractor import InvoiceExtractor
from src.ocr.cache import CachingOcrEngine
from tests.conftest import MINIMAL_PDF, CountingEngine, ScriptedProvider, sample_invoice

# PNG header plus filler, used as the "this is not an invoice" upload.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def extractor_answering(invoice_json: str) -> InvoiceExtractor:
    """An extractor whose model always answers with the given invoice."""
    return InvoiceExtractor(ScriptedProvider(invoice_json, invoice_json))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # The counting engine stands in for tesseract here, wrapped the same way
    # startup wraps the real one. Reading a real PDF is what
    # tests/test_tesseract.py is for. The extractor is scripted for the same
    # reason: these tests are about the endpoint, not about a model.
    app.state.ocr = CachingOcrEngine(CountingEngine())
    app.state.extractor = extractor_answering(sample_invoice().model_dump_json())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ready_client:
        yield ready_client


async def test_health_answers_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_pdf_is_accepted_read_and_checked(client: AsyncClient) -> None:
    files = {"file": ("invoice.pdf", MINIMAL_PDF, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "invoice.pdf"
    assert body["size_bytes"] == len(MINIMAL_PDF)
    assert body["reading"] == {"engine": "counting", "pages": 1, "text_lines": 1}
    assert body["valid"] is True
    assert body["violations"] == []
    assert body["invoice"]["number"]["value"] == "R-2026-0042"
    # Money leaves as a string, all the way out through the API.
    assert body["invoice"]["totals"]["gross_total"]["value"] == "240.00"


async def test_an_invoice_that_does_not_add_up_comes_back_whole(client: AsyncClient) -> None:
    """The broken one is the one somebody has to look at, so it is not thrown away."""
    payload = sample_invoice().model_dump(mode="json")
    payload["totals"]["gross_total"]["value"] = "999.00"
    app.state.extractor = extractor_answering(json.dumps(payload))
    files = {"file": ("wrong.pdf", MINIMAL_PDF, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert [v["rule"] for v in body["violations"]] == ["BR-CO-15", "BR-CO-16"]
    assert body["invoice"]["totals"]["gross_total"]["value"] == "999.00"

    first = body["violations"][0]
    assert first["bt"] == "BT-112"
    assert first["field"] == "totals.gross_total"
    assert first["expected"] == "240.00"
    assert first["actual"] == "999.00"


async def test_without_a_model_the_answer_says_so(client: AsyncClient) -> None:
    """No key is a configuration problem, and the message names the variable."""
    app.state.extractor = None
    files = {"file": ("invoice.pdf", MINIMAL_PDF, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "llm_not_configured"
    assert "OPENAI_API_KEY" in body["error"]["message"]


async def test_image_is_rejected_with_415(client: AsyncClient) -> None:
    files = {"file": ("scan.png", PNG_BYTES, "image/png")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "not_a_pdf"
    assert "PDF" in error["message"]


async def test_pdf_name_and_content_type_are_not_enough(client: AsyncClient) -> None:
    """Both are set by the client and both are easy to fake, so bytes decide."""
    files = {"file": ("invoice.pdf", PNG_BYTES, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "not_a_pdf"


async def test_file_over_the_limit_is_rejected_with_413(client: AsyncClient) -> None:
    too_big = MINIMAL_PDF + b"0" * MAX_UPLOAD_BYTES
    files = {"file": ("huge.pdf", too_big, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


async def test_file_exactly_at_the_limit_is_accepted(client: AsyncClient) -> None:
    """Ten megabytes is allowed. The rejection starts one byte later."""
    at_limit = MINIMAL_PDF + b"0" * (MAX_UPLOAD_BYTES - len(MINIMAL_PDF))
    files = {"file": ("big.pdf", at_limit, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 200
    assert response.json()["size_bytes"] == MAX_UPLOAD_BYTES


async def test_request_without_a_file_is_a_validation_error(client: AsyncClient) -> None:
    response = await client.post("/extract")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_the_same_file_twice_is_read_once(client: AsyncClient) -> None:
    """The cache sits in front of the engine, so a repeat upload costs nothing."""
    inner = CountingEngine()
    app.state.ocr = CachingOcrEngine(inner)
    files = {"file": ("invoice.pdf", MINIMAL_PDF, "application/pdf")}

    await client.post("/extract", files=files)
    await client.post("/extract", files=files)

    assert inner.calls == 1


async def test_service_refuses_to_start_on_an_unknown_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in OCR_ENGINE stops the service, it does not wait for an upload."""
    monkeypatch.setenv("OCR_ENGINE", "nonsense")

    with pytest.raises(UnknownOcrEngineError):
        async with lifespan(app):
            pass


async def test_startup_puts_a_caching_engine_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_ENGINE", "tesseract")

    async with lifespan(app):
        assert app.state.ocr.name == "tesseract"


async def test_no_model_key_does_not_take_the_service_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading PDFs still works. The upload gets a clear answer instead."""
    monkeypatch.setenv("OCR_ENGINE", "tesseract")

    async with lifespan(app):
        assert app.state.ocr.name == "tesseract"
        assert app.state.extractor is None


async def test_a_model_key_builds_the_extractor_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async with lifespan(app):
        assert isinstance(app.state.extractor, InvoiceExtractor)
