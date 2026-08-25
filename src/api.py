"""FastAPI app. Wave 0 accepts an upload and checks it, nothing is extracted yet."""

from __future__ import annotations

from typing import Annotated, Final, Literal

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.errors import FileTooLargeError, InvoiceError, NotAPdfError
from src.logs import configure_logging, get_logger

# 10 MB. Anything bigger is a mistake or an attack, not an invoice.
MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024

# Every PDF starts with these bytes. File name and content type are set by the
# client and are easy to fake, so the bytes decide.
PDF_SIGNATURE: Final = b"%PDF-"

# Read in pieces, so an oversized upload is stopped before it is fully in memory.
READ_CHUNK_BYTES: Final = 64 * 1024

configure_logging()
log = get_logger()

app = FastAPI(
    title="invoice-en16931",
    version="0.1.0",
    summary="PDF invoice in, EN 16931 data out",
)


class Health(BaseModel):
    """Answer of GET /health."""

    status: Literal["ok"]


class ExtractAccepted(BaseModel):
    """Answer of POST /extract in wave 0. Invoice fields arrive in wave 3."""

    status: Literal["accepted"]
    filename: str
    size_bytes: int


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
    },
)
async def extract(file: Annotated[UploadFile, File()]) -> ExtractAccepted:
    """Take a PDF invoice. Wave 0 checks the upload and stops there."""
    data = await _read_within_limit(file)
    if not data.startswith(PDF_SIGNATURE):
        raise NotAPdfError("file is not a PDF, the PDF signature is missing")

    name = file.filename or "upload.pdf"
    log.info("upload_accepted", filename=name, size_bytes=len(data))
    return ExtractAccepted(status="accepted", filename=name, size_bytes=len(data))
