"""Errors the service raises on purpose. Anything else is a bug."""

from __future__ import annotations


class InvoiceError(Exception):
    """Base class for every error we raise ourselves.

    Each error carries the HTTP status and a short code, so the API can turn any
    of them into a response without a chain of isinstance checks.
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotAPdfError(InvoiceError):
    """The upload does not start with the PDF signature."""

    status_code = 415
    code = "not_a_pdf"


class FileTooLargeError(InvoiceError):
    """The upload is over the size limit."""

    status_code = 413
    code = "file_too_large"


class UnknownOcrEngineError(InvoiceError):
    """OCR_ENGINE names an engine that does not exist.

    Raised while the service starts, so a typo in the config is found there and
    not on the first upload of the day.
    """

    status_code = 500
    code = "unknown_ocr_engine"


class OcrFailedError(InvoiceError):
    """The page could not be read: the PDF is broken or a tool failed."""

    status_code = 422
    code = "ocr_failed"
