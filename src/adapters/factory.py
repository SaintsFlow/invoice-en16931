"""The one place that knows which adapters exist."""

from __future__ import annotations

import os
from typing import Final

from src.adapters.base import ERPAdapter
from src.adapters.file import FileAdapter
from src.adapters.mock_erp import MockErpAdapter, url_from_env
from src.errors import UnknownAdapterError

FILE: Final = "file"
MOCK_ERP: Final = "mock_erp"

AVAILABLE: Final = (FILE, MOCK_ERP)


def create_adapter(name: str | None = None) -> ERPAdapter:
    """Build the adapter ERP_ADAPTER asks for.

    Called while the service starts, the same as the OCR engine, so a typo in the
    config stops it there instead of on the first invoice somebody delivers.
    """
    # An empty variable counts as "not set", so ERP_ADAPTER= falls back to the
    # default rather than asking for an adapter with no name.
    chosen = (name or os.environ.get("ERP_ADAPTER") or FILE).strip().lower()

    if chosen == FILE:
        return FileAdapter()

    if chosen == MOCK_ERP:
        return MockErpAdapter(url_from_env())

    raise UnknownAdapterError(
        f"ERP_ADAPTER={chosen!r} is not an adapter. Available: {', '.join(AVAILABLE)}."
    )
