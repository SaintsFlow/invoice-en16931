"""Choosing an engine. A wrong name has to be obvious right away."""

from __future__ import annotations

import pytest

from src.errors import UnknownOcrEngineError
from src.ocr.factory import create_engine
from src.ocr.tesseract import TesseractEngine


def test_tesseract_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCR_ENGINE", raising=False)
    monkeypatch.delenv("OCR_LANGS", raising=False)

    engine = create_engine()

    assert isinstance(engine, TesseractEngine)
    assert engine.langs == "eng+deu"


def test_languages_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    monkeypatch.setenv("OCR_LANGS", "deu")

    engine = create_engine()

    assert isinstance(engine, TesseractEngine)
    assert engine.langs == "deu"


def test_an_unknown_name_names_what_is_available() -> None:
    with pytest.raises(UnknownOcrEngineError) as failure:
        create_engine("nonsense")

    assert "nonsense" in failure.value.message
    assert "tesseract" in failure.value.message


def test_paddle_says_it_is_not_built_yet() -> None:
    with pytest.raises(UnknownOcrEngineError) as failure:
        create_engine("paddle")

    assert "wave 6" in failure.value.message


def test_the_name_is_read_without_case_or_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_ENGINE", "  TesserAct ")

    assert isinstance(create_engine(), TesseractEngine)
