"""What every OCR engine has to return. Engines differ, the result does not."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Where a piece of text sits, in pixels of the rendered page image."""

    left: int
    top: int
    width: int
    height: int


class OcrLine(BaseModel):
    """One line of text, kept whole.

    A table row is a line. Flattening the page into a single stream of words is
    what makes line items fall apart later, so the line is the smallest unit we
    hand on.
    """

    text: str
    box: BoundingBox
    confidence: float = Field(ge=0.0, le=100.0)


class OcrPage(BaseModel):
    """One page of the document. Pages are numbered from 1, as people count."""

    number: int = Field(ge=1)
    width: int
    height: int
    lines: list[OcrLine]

    @property
    def text(self) -> str:
        """The page as plain text, one line per recognised line."""
        return "\n".join(line.text for line in self.lines)


class OcrResult(BaseModel):
    """Everything an engine could read out of one PDF."""

    engine: str
    pages: list[OcrPage]

    @property
    def text(self) -> str:
        """The whole document as plain text, pages separated by a blank line."""
        return "\n\n".join(page.text for page in self.pages)

    @property
    def line_count(self) -> int:
        return sum(len(page.lines) for page in self.pages)


class OcrEngine(ABC):
    """The contract wave 3 depends on. Tesseract today, paddle in wave 6."""

    name: str = "base"

    @abstractmethod
    async def read(self, pdf: bytes) -> OcrResult:
        """Read the PDF and return its text with the layout kept."""
