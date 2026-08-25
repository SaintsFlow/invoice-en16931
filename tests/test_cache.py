"""The OCR cache: read a file once, answer from memory after that."""

from __future__ import annotations

from src.ocr.cache import CachingOcrEngine
from tests.conftest import MINIMAL_PDF, CountingEngine

OTHER_PDF = MINIMAL_PDF + b"% a different file\n"


async def test_the_same_file_is_read_only_once() -> None:
    inner = CountingEngine()
    engine = CachingOcrEngine(inner)

    first = await engine.read(MINIMAL_PDF)
    second = await engine.read(MINIMAL_PDF)

    assert inner.calls == 1
    assert second == first


async def test_another_file_is_read_again() -> None:
    inner = CountingEngine()
    engine = CachingOcrEngine(inner)

    await engine.read(MINIMAL_PDF)
    await engine.read(OTHER_PDF)

    assert inner.calls == 2


async def test_the_oldest_entry_is_dropped_when_the_cache_is_full() -> None:
    inner = CountingEngine()
    engine = CachingOcrEngine(inner, max_entries=2)

    await engine.read(MINIMAL_PDF)
    await engine.read(OTHER_PDF)
    await engine.read(OTHER_PDF + b"third\n")
    # The first file is out of the cache by now, so it has to be read again.
    await engine.read(MINIMAL_PDF)

    assert inner.calls == 4


async def test_the_cache_keeps_the_engine_name() -> None:
    engine = CachingOcrEngine(CountingEngine())

    assert engine.name == "counting"
