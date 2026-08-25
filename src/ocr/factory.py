"""The one place that knows which OCR engines exist."""

from __future__ import annotations

import os
from typing import Final

from src.errors import UnknownOcrEngineError
from src.ocr.base import OcrEngine
from src.ocr.tesseract import DEFAULT_LANGS, TesseractEngine

TESSERACT: Final = "tesseract"
PADDLE: Final = "paddle"

AVAILABLE: Final = (TESSERACT,)


def create_engine(name: str | None = None, langs: str | None = None) -> OcrEngine:
    """Build the engine OCR_ENGINE asks for.

    Called while the service starts, so a wrong name stops it right there
    instead of failing on the first upload of the day.
    """
    # An empty variable counts as "not set", so OCR_ENGINE= falls back to the
    # default instead of asking for an engine with no name.
    chosen = (name or os.environ.get("OCR_ENGINE") or TESSERACT).strip().lower()
    languages = langs or os.environ.get("OCR_LANGS") or DEFAULT_LANGS

    if chosen == TESSERACT:
        return TesseractEngine(langs=languages)

    if chosen == PADDLE:
        raise UnknownOcrEngineError(
            "OCR_ENGINE=paddle is not built yet, it arrives in wave 6. Use tesseract."
        )

    raise UnknownOcrEngineError(
        f"OCR_ENGINE={chosen!r} is not an engine. Available: {', '.join(AVAILABLE)}."
    )
