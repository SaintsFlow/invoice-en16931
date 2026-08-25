"""Wave 0 API tests: the upload is checked, nothing is extracted yet."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import MAX_UPLOAD_BYTES, app

# Enough of a PDF for the signature check. Real sample invoices come in wave 6.
MINIMAL_PDF = b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

# PNG header plus filler, used as the "this is not an invoice" upload.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ready_client:
        yield ready_client


async def test_health_answers_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_pdf_is_accepted(client: AsyncClient) -> None:
    files = {"file": ("invoice.pdf", MINIMAL_PDF, "application/pdf")}

    response = await client.post("/extract", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["filename"] == "invoice.pdf"
    assert body["size_bytes"] == len(MINIMAL_PDF)


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
