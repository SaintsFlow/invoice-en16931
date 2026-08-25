"""FastAPI app. The upload is checked and read; the fields come in wave 3."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Final, Literal

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.errors import (
    FileTooLargeError,
    InvoiceError,
    LlmConfigError,
    NotAPdfError,
    OcrFailedError,
)
from src.extract.extractor import InvoiceExtractor
from src.extract.openai import OpenAIProvider
from src.logs import configure_logging, get_logger
from src.ocr.base import OcrEngine
from src.ocr.cache import CachingOcrEngine
from src.ocr.factory import create_engine
from src.schema import Invoice
from src.validate import Violation, check

# 10 MB. Anything bigger is a mistake or an attack, not an invoice.
MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024

# Every PDF starts with these bytes. File name and content type are set by the
# client and are easy to fake, so the bytes decide.
PDF_SIGNATURE: Final = b"%PDF-"

# Read in pieces, so an oversized upload is stopped before it is fully in memory.
READ_CHUNK_BYTES: Final = 64 * 1024

configure_logging()
log = get_logger()


@asynccontextmanager
async def lifespan(service: FastAPI) -> AsyncIterator[None]:
    """Build the OCR engine and, if it is configured, the extractor.

    A wrong OCR_ENGINE stops the service here, with a readable message, instead
    of failing on the first upload of the day.

    A missing model key does not stop anything. The service still reads PDFs, and
    an upload gets a clear answer saying the model is not configured. Refusing to
    start would take the OCR down with it for no reason.
    """
    engine = CachingOcrEngine(create_engine())
    service.state.ocr = engine

    try:
        service.state.extractor = InvoiceExtractor(OpenAIProvider.from_env())
        model_ready = True
    except LlmConfigError as unconfigured:
        service.state.extractor = None
        model_ready = False
        log.warning("extractor_not_configured", reason=unconfigured.message)

    log.info("service_started", ocr_engine=engine.name, extractor=model_ready)
    yield


app = FastAPI(
    title="invoice-en16931",
    version="0.1.0",
    summary="PDF invoice in, EN 16931 data out",
    lifespan=lifespan,
)


class Health(BaseModel):
    """Answer of GET /health."""

    status: Literal["ok"]


class ReadingReport(BaseModel):
    """What the OCR step saw, kept next to the result so a bad read is visible."""

    engine: str
    pages: int
    text_lines: int


class Extracted(BaseModel):
    """Answer of POST /extract.

    The invoice is here whether it passed the checks or not. An invoice that does
    not add up is exactly the one somebody needs to look at, and throwing it away
    would leave them with nothing to correct.
    """

    filename: str
    size_bytes: int
    reading: ReadingReport
    valid: bool
    violations: list[Violation]
    invoice: Invoice


class ErrorBody(BaseModel):
    """What went wrong, in a form a client can branch on."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """One shape for every error the API returns."""

    error: ErrorBody


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build an error answer. Callers never leak internals into the message."""
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(InvoiceError)
async def handle_invoice_error(request: Request, exc: Exception) -> JSONResponse:
    """Turn our own errors into the single error shape."""
    if not isinstance(exc, InvoiceError):
        raise exc
    log.warning("upload_rejected", code=exc.code, path=request.url.path)
    return _error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI reports a malformed request in its own shape. Make it ours."""
    log.warning("request_invalid", path=request.url.path)
    return _error_response(
        422,
        "invalid_request",
        "send the PDF as a multipart field named 'file'",
    )


@app.get("/health")
async def health() -> Health:
    """Liveness check for compose and for whatever runs the container."""
    return Health(status="ok")


async def _read_within_limit(upload: UploadFile) -> bytes:
    """Read the upload and stop as soon as it crosses the size limit."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(READ_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise FileTooLargeError(f"file is larger than {limit_mb} MB")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post(
    "/extract",
    responses={
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def extract(request: Request, file: Annotated[UploadFile, File()]) -> Extracted:
    """Take a PDF invoice, read it, pull out the fields and check them."""
    data = await _read_within_limit(file)
    if not data.startswith(PDF_SIGNATURE):
        raise NotAPdfError("file is not a PDF, the PDF signature is missing")

    name = file.filename or "upload.pdf"
    log.info("upload_accepted", filename=name, size_bytes=len(data))

    read = await _engine_of(request.app).read(data)
    invoice = await _extractor_of(request.app).extract(read)
    report = check(invoice)

    log.info(
        "invoice_checked",
        filename=name,
        valid=report.valid,
        violations=[violation.rule for violation in report.violations],
    )
    return Extracted(
        filename=name,
        size_bytes=len(data),
        reading=ReadingReport(
            engine=read.engine, pages=len(read.pages), text_lines=read.line_count
        ),
        valid=report.valid,
        violations=report.violations,
        invoice=invoice,
    )


def _engine_of(service: FastAPI) -> OcrEngine:
    """Take the engine the startup put aside."""
    engine = getattr(service.state, "ocr", None)
    if not isinstance(engine, OcrEngine):
        raise OcrFailedError("the OCR engine is not ready")
    return engine


def _extractor_of(service: FastAPI) -> InvoiceExtractor:
    """Take the extractor the startup put aside, or say plainly that there is none."""
    extractor = getattr(service.state, "extractor", None)
    if not isinstance(extractor, InvoiceExtractor):
        raise LlmConfigError(
            "the service cannot read fields out of an invoice: no model is configured. "
            "Set OPENAI_API_KEY, and OPENAI_BASE_URL if the model is not OpenAI."
        )
    return extractor
