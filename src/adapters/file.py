"""Writing the invoice to disk, in both formats.

The plain one. Useful on its own for a folder somebody watches, and useful as the
thing to compare a real ERP adapter against when its answers look wrong.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Final

from src.adapters.base import AdapterResult, ERPAdapter
from src.render import json_out, ubl
from src.schema import Invoice

DEFAULT_OUTPUT_DIR: Final = Path("./out")

# Anything that is not a letter, a digit, a dash or a dot becomes a dash. Invoice
# numbers arrive from a scan and can carry slashes, spaces, whatever the printer
# put there, and a slash in a file name silently writes somewhere else.
_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")


class FileAdapter(ERPAdapter):
    """Writes <number>.xml and <number>.json into OUTPUT_DIR."""

    name = "file"

    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir or _output_dir_from_env()

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    async def deliver(self, invoice: Invoice) -> AdapterResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(invoice.number.value)

        xml_path = self._output_dir / f"{stem}.xml"
        xml_path.write_text(ubl.render(invoice), encoding="utf-8")

        json_path = self._output_dir / f"{stem}.json"
        flat = json_out.render(invoice)
        json_path.write_text(json.dumps(flat, indent=2, ensure_ascii=False), encoding="utf-8")

        return AdapterResult(
            adapter=self.name,
            reference=str(xml_path),
            detail=f"wrote {xml_path.name} and {json_path.name}",
        )


def safe_stem(number: str) -> str:
    """A file name built from an invoice number, with nothing surprising in it."""
    cleaned = _UNSAFE.sub("-", number.strip()).strip("-.")
    return cleaned or "invoice"


def _output_dir_from_env() -> Path:
    raw = os.environ.get("OUTPUT_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_OUTPUT_DIR
