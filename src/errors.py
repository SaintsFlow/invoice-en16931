"""Errors the service raises on purpose. Anything else is a bug."""

from __future__ import annotations

from collections.abc import Sequence


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


class LlmConfigError(InvoiceError):
    """The model is not configured: no key, or a setting that makes no sense."""

    status_code = 500
    code = "llm_not_configured"


class LlmRequestError(InvoiceError):
    """The model could not be reached, or answered with something unusable.

    502 rather than 500: the fault is upstream, and a caller can decide to retry.
    """

    status_code = 502
    code = "llm_request_failed"


class InvoiceNotValidError(InvoiceError):
    """An invoice that breaks the rules was offered to an adapter.

    422 rather than 500: nothing is broken here, the document is. Carries the
    violations so the caller sees what to correct rather than just being refused.
    """

    status_code = 422
    code = "invoice_not_valid"

    def __init__(self, message: str, violations: Sequence[object] = ()) -> None:
        super().__init__(message)
        self.violations = list(violations)


class AdapterFailedError(InvoiceError):
    """The receiving end refused the invoice or could not be reached.

    502, the same reasoning as a model that will not answer: the fault is on the
    other side of the wire and a caller may want to try again later.
    """

    status_code = 502
    code = "adapter_failed"


class UnknownAdapterError(InvoiceError):
    """ERP_ADAPTER names something that does not exist.

    Raised while the service starts, so a typo is found there and not on the first
    invoice somebody tries to deliver.
    """

    status_code = 500
    code = "unknown_adapter"


class ExtractionFailedError(InvoiceError):
    """The model answered, but never with an invoice that fits the schema.

    Carries the list of problems as well as the message. The message is what a
    caller sees; the problems are what the retry quotes back to the model and
    what a human needs to see which field went wrong.
    """

    status_code = 422
    code = "extraction_failed"

    def __init__(self, message: str, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.problems = list(problems)
