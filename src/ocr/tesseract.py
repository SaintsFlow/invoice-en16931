"""Tesseract engine. Poppler renders the pages, tesseract reads them."""

from __future__ import annotations

import asyncio
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from src.errors import OcrFailedError
from src.logs import get_logger
from src.ocr.base import BoundingBox, OcrEngine, OcrLine, OcrPage, OcrResult

log = get_logger()

DEFAULT_LANGS: Final = "eng+deu"

# 300 dpi is what tesseract is tuned for. Less blurs small print, more only
# costs time.
DEFAULT_DPI: Final = 300

# psm 6 treats the page as one block of uniform text, which keeps table rows
# in one piece. psm 3 pulls columns apart and scatters the line items.
PAGE_SEGMENTATION_MODE: Final = "6"

# A scanned invoice is done in seconds. The limit is here so a broken file
# cannot hold a worker forever.
TIMEOUT_SECONDS: Final = 120.0


@dataclass(frozen=True)
class _Word:
    """One word from the tesseract TSV output."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float


class TesseractEngine(OcrEngine):
    """Reads a PDF by rendering it to images first."""

    name = "tesseract"

    def __init__(self, langs: str = DEFAULT_LANGS, dpi: int = DEFAULT_DPI) -> None:
        self.langs = langs
        self.dpi = dpi

    async def read(self, pdf: bytes) -> OcrResult:
        """Render every page, read it, and return the lines with their boxes."""
        with TemporaryDirectory() as workdir:
            work = Path(workdir)
            source = work / "input.pdf"
            source.write_bytes(pdf)

            images = await self._render(source, work / "page")
            pages = [
                await self._read_page(image, number) for number, image in enumerate(images, start=1)
            ]

        result = OcrResult(engine=self.name, pages=pages)
        log.info(
            "ocr_finished",
            engine=self.name,
            langs=self.langs,
            pages=len(result.pages),
            lines=result.line_count,
        )
        return result

    async def _render(self, source: Path, prefix: Path) -> list[Path]:
        """Turn the PDF into one PNG per page."""
        await _run("pdftoppm", "-r", str(self.dpi), "-png", str(source), str(prefix))
        images = sorted(prefix.parent.glob(f"{prefix.name}-*.png"))
        if not images:
            raise OcrFailedError("the PDF has no pages that could be rendered")
        return images

    async def _read_page(self, image: Path, number: int) -> OcrPage:
        """Read one page. The TSV output carries a box for every word."""
        raw = await _run(
            "tesseract",
            str(image),
            "stdout",
            "-l",
            self.langs,
            "--psm",
            PAGE_SEGMENTATION_MODE,
            "tsv",
        )
        return _parse_tsv(raw, number)


async def _run(*args: str) -> bytes:
    """Run a tool and return its stdout. Both tools are shipped in the image."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        raise OcrFailedError(f"{args[0]} did not finish in {TIMEOUT_SECONDS:.0f} seconds") from None

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise OcrFailedError(f"{args[0]} failed: {detail[:200]}")
    return stdout


def _parse_tsv(raw: bytes, number: int) -> OcrPage:
    """Group the words tesseract found back into lines.

    Level 1 rows describe the page, level 5 rows are words. Words that belong
    to the same block, paragraph and line form one line of text.
    """
    rows = csv.reader(
        raw.decode("utf-8", errors="replace").splitlines(),
        delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    header = next(rows, None)
    if header is None:
        raise OcrFailedError("tesseract returned nothing for this page")
    column = {name: position for position, name in enumerate(header)}

    page_width = 0
    page_height = 0
    grouped: dict[tuple[str, str, str], list[_Word]] = defaultdict(list)

    for row in rows:
        if len(row) < len(header):
            continue
        level = row[column["level"]]

        if level == "1":
            page_width = int(row[column["width"]])
            page_height = int(row[column["height"]])
            continue
        if level != "5":
            continue

        text = row[column["text"]].strip()
        confidence = float(row[column["conf"]])
        # Tesseract reports -1 for boxes it found but could not read.
        if not text or confidence < 0:
            continue

        key = (row[column["block_num"]], row[column["par_num"]], row[column["line_num"]])
        grouped[key].append(
            _Word(
                text=text,
                left=int(row[column["left"]]),
                top=int(row[column["top"]]),
                width=int(row[column["width"]]),
                height=int(row[column["height"]]),
                confidence=confidence,
            )
        )

    lines = [_join(words) for words in grouped.values()]
    lines.sort(key=lambda line: (line.box.top, line.box.left))
    return OcrPage(number=number, width=page_width, height=page_height, lines=lines)


def _join(words: list[_Word]) -> OcrLine:
    """Make one line out of the words tesseract put on it."""
    ordered = sorted(words, key=lambda word: word.left)
    left = min(word.left for word in ordered)
    top = min(word.top for word in ordered)
    right = max(word.left + word.width for word in ordered)
    bottom = max(word.top + word.height for word in ordered)

    return OcrLine(
        text=" ".join(word.text for word in ordered),
        box=BoundingBox(left=left, top=top, width=right - left, height=bottom - top),
        confidence=sum(word.confidence for word in ordered) / len(ordered),
    )
