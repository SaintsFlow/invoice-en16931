"""OCR behind an interface: tesseract today, paddle in wave 6."""

from src.ocr.base import BoundingBox, OcrEngine, OcrLine, OcrPage, OcrResult
from src.ocr.cache import CachingOcrEngine
from src.ocr.factory import create_engine

__all__ = [
    "BoundingBox",
    "CachingOcrEngine",
    "OcrEngine",
    "OcrLine",
    "OcrPage",
    "OcrResult",
    "create_engine",
]
