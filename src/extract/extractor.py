"""Turning OCR text into an invoice. The only place in the service that calls a model.

Nothing here trusts the answer. The model is asked for a shape, the answer is parsed
and validated against the schema of wave 2, and a bad answer buys exactly one retry
with the validation error quoted back. What survives that is a well formed invoice.
Whether it is a correct invoice, whether the sums add up, is decided later.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from src.errors import ExtractionFailedError
from src.extract.base import LlmProvider, Message
from src.logs import get_logger
from src.ocr.base import OcrResult
from src.schema import Invoice, describe_errors

log = get_logger()

PROMPT_PATH: Final = Path(__file__).resolve().parents[2] / "prompts" / "extract.md"

# Roughly fifteen pages of invoice text. A long multi page scan otherwise eats the
# context window and the budget with it, and pages sixteen and on are almost never
# where the totals live.
DEFAULT_MAX_OCR_CHARS: Final = 20_000

# One try and one retry. A second retry has never been the thing that fixed an
# answer, it only doubles the bill.
ATTEMPTS: Final = 2

# These two say which specification the document follows. They are ours, they are
# not printed on the paper, and a model that returns them anyway is overruled.
OURS_NOT_THE_MODELS: Final = ("customization_id", "profile_id")


class InvoiceExtractor:
    """Asks the model for the fields of one invoice and checks what comes back."""

    def __init__(
        self,
        provider: LlmProvider,
        *,
        prompt_path: Path = PROMPT_PATH,
        max_ocr_chars: int | None = None,
    ) -> None:
        self._provider = provider
        self._prompt_path = prompt_path
        self._max_ocr_chars = max_ocr_chars if max_ocr_chars is not None else _max_chars_from_env()

    async def extract(self, ocr: OcrResult) -> Invoice:
        """Read the fields out of an OCR result.

        Raises ExtractionFailedError when the model could not produce an invoice
        that fits the schema, even after the retry.
        """
        text = self._trim(ocr.text)
        schema = Invoice.model_json_schema()
        messages = [
            Message(role="system", content=_prompt(self._prompt_path)),
            Message(role="user", content=text),
        ]

        problems: list[str] = []
        for attempt in range(1, ATTEMPTS + 1):
            answer = await self._provider.complete(messages, schema)
            try:
                invoice = _invoice_of(answer)
            except ExtractionFailedError as refused:
                problems = refused.problems
                log.warning(
                    "extraction_answer_refused",
                    attempt=attempt,
                    provider=self._provider.name,
                    problems=problems[:5],
                )
                messages = [
                    *messages,
                    Message(role="assistant", content=answer),
                    Message(role="user", content=_complaint(problems)),
                ]
                continue

            log.info(
                "invoice_extracted",
                attempt=attempt,
                provider=self._provider.name,
                lines=len(invoice.lines),
            )
            return invoice

        raise ExtractionFailedError(
            f"the model did not return a usable invoice in {ATTEMPTS} attempts",
            problems,
        )

    def _trim(self, text: str) -> str:
        """Cut the text down to what we are willing to pay for."""
        if len(text) <= self._max_ocr_chars:
            return text
        log.info("ocr_text_trimmed", had=len(text), kept=self._max_ocr_chars)
        return text[: self._max_ocr_chars]


@cache
def _prompt(path: Path) -> str:
    """Read the prompt from disk once. It does not change while the service runs."""
    return path.read_text(encoding="utf-8")


def _max_chars_from_env() -> int:
    """Read MAX_OCR_CHARS, and treat nonsense as "not set" instead of crashing."""
    raw = os.environ.get("MAX_OCR_CHARS", "").strip()
    if not raw:
        return DEFAULT_MAX_OCR_CHARS
    try:
        chars = int(raw)
    except ValueError:
        log.warning("max_ocr_chars_ignored", value=raw)
        return DEFAULT_MAX_OCR_CHARS
    return chars if chars > 0 else DEFAULT_MAX_OCR_CHARS


def _invoice_of(answer: str) -> Invoice:
    """Parse one answer and build an invoice, or say precisely what is wrong with it."""
    try:
        # parse_float=Decimal is load bearing. Money that arrives as a JSON number
        # becomes a float without it, and the schema refuses floats in money on
        # purpose: a float cannot hold cents.
        payload = json.loads(answer, parse_float=Decimal)
    except json.JSONDecodeError as broken:
        raise ExtractionFailedError(
            "the answer is not JSON", [f"line {broken.lineno}: {broken.msg}"]
        ) from broken

    if not isinstance(payload, dict):
        raise ExtractionFailedError(
            "the answer is not a JSON object", [f"got {type(payload).__name__}"]
        )

    fields = _drop_unreadable(payload)
    if not isinstance(fields, dict):
        raise ExtractionFailedError("the answer is not a JSON object", ["it collapsed to null"])
    for key in OURS_NOT_THE_MODELS:
        fields.pop(key, None)

    try:
        return Invoice.model_validate(fields)
    except ValidationError as wrong:
        raise ExtractionFailedError(
            "the answer does not fit the invoice schema", describe_errors(Invoice, wrong)
        ) from wrong


def _drop_unreadable(value: object) -> object:
    """Collapse a field the model could not read into a plain null.

    The prompt asks for null when a value is not visible, and models answer that
    two ways: `null` outright, or the wrapper with an empty value in it. Both mean
    the same thing, so both become null before validation. A required field that
    goes missing this way still fails validation, and that is the right outcome.
    """
    if isinstance(value, dict):
        if "value" in value and value["value"] is None:
            return None
        return {key: _drop_unreadable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_drop_unreadable(item) for item in value]
    return value


def _complaint(problems: list[str]) -> str:
    """Tell the model what was wrong, so the retry has something to go on."""
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        "That answer could not be used:\n"
        f"{listed}\n"
        "Send the corrected JSON object and nothing else. Where you cannot see a "
        "value in the text, keep it null instead of inventing one."
    )
