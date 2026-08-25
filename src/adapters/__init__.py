"""Delivering a finished invoice. Nothing invalid gets past ERPAdapter.send."""

from src.adapters.base import AdapterResult, ERPAdapter
from src.adapters.factory import AVAILABLE, create_adapter
from src.adapters.file import FileAdapter
from src.adapters.mock_erp import MockErpAdapter

__all__ = [
    "AVAILABLE",
    "AdapterResult",
    "ERPAdapter",
    "FileAdapter",
    "MockErpAdapter",
    "create_adapter",
]
