"""Remembering OCR results, so the same file is never read twice."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Final

from src.logs import get_logger
from src.ocr.base import OcrEngine, OcrResult

log = get_logger()

# Roughly a working session worth of invoices. Results are small, the pages
# hold text and boxes, not images.
DEFAULT_MAX_ENTRIES: Final = 32


class CachingOcrEngine(OcrEngine):
    """Wraps an engine and keeps the results of the files it has already read.

    The key is the sha256 of the file content, not its name: the same invoice
    turns up as scan.pdf, scan(1).pdf and RE-2026-0042.pdf.

    The cache lives in the process, so a restart empties it. That is enough for
    what it is for, saving repeated work inside one run, and it needs no volume.
    """

    def __init__(self, inner: OcrEngine, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._inner = inner
        self._max_entries = max_entries
        self._entries: OrderedDict[str, OcrResult] = OrderedDict()
        self.name = inner.name

    async def read(self, pdf: bytes) -> OcrResult:
        digest = hashlib.sha256(pdf).hexdigest()

        remembered = self._entries.get(digest)
        if remembered is not None:
            self._entries.move_to_end(digest)
            log.info("ocr_cache_hit", digest=digest[:12], engine=self.name)
            return remembered

        result = await self._inner.read(pdf)
        self._entries[digest] = result
        if len(self._entries) > self._max_entries:
            dropped, _ = self._entries.popitem(last=False)
            log.info("ocr_cache_dropped", digest=dropped[:12])
        return result
