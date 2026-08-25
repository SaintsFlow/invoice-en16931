"""Build the sample invoices the tests run against.

Every name, address and VAT number here is made up. No real invoice and no real
company data goes into this repository.

The PDF is written by hand with the standard library, so the project keeps its
dependency list short. Wave 6 grows this into five or six invoices with
different layouts.

Run it with: python3 scripts/make_samples.py
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PAGE_WIDTH = 595
PAGE_HEIGHT = 842

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


@dataclass(frozen=True)
class TextLine:
    """One line of text placed on the page. Origin is the bottom left corner."""

    x: float
    y: float
    text: str
    size: float = 11.0
    bold: bool = False


def _escape(text: str) -> str:
    """Backslashes and brackets carry meaning inside a PDF string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: Sequence[TextLine]) -> bytes:
    drawn = [
        f"BT {'/F2' if line.bold else '/F1'} {line.size} Tf "
        f"{line.x} {line.y} Td ({_escape(line.text)}) Tj ET"
        for line in lines
    ]
    return "\n".join(drawn).encode("ascii")


def build_pdf(lines: Sequence[TextLine]) -> bytes:
    """Assemble a one page PDF: catalog, page, two fonts and the drawing."""
    content = _content_stream(lines)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
        f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    # The cross reference table has to point at the byte offset of every object,
    # so it is built after the objects are laid out.
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def invoice_01() -> list[TextLine]:
    """An Austrian style invoice: two VAT rates, three line items.

    German without umlauts on purpose. Helvetica would need a wider encoding for
    them, and the OCR test does not get any better from the extra characters.
    """
    rows = [
        ("1", "Beratung pro Stunde", "10", "120,00", "20", "1200,00"),
        ("2", "Lizenz Basis Jahr", "2", "250,00", "20", "500,00"),
        ("3", "Versand pauschal", "1", "35,00", "10", "35,00"),
    ]

    lines = [
        TextLine(50, 800, "Muster Handels GmbH", size=14, bold=True),
        TextLine(50, 782, "Beispielstrasse 12, 1010 Wien"),
        TextLine(50, 766, "UID: ATU12345678"),
        TextLine(400, 800, "RECHNUNG", size=18, bold=True),
        TextLine(50, 720, "Rechnungsempfaenger:", bold=True),
        TextLine(50, 704, "Testkunde AG"),
        TextLine(50, 688, "Musterweg 3, 5020 Salzburg"),
        TextLine(50, 672, "UID: ATU87654321"),
        TextLine(50, 630, "Rechnungsnummer: 2026-0042"),
        TextLine(50, 612, "Rechnungsdatum: 14.03.2026"),
        TextLine(50, 594, "Faelligkeitsdatum: 13.04.2026"),
        TextLine(50, 576, "Waehrung: EUR"),
    ]

    header_y = 520
    columns = (50, 90, 300, 360, 445, 500)
    headers = ("Pos", "Bezeichnung", "Menge", "Einzelpreis", "USt %", "Betrag")
    lines += [
        TextLine(x, header_y, title, bold=True) for x, title in zip(columns, headers, strict=True)
    ]

    for index, row in enumerate(rows):
        row_y = header_y - 26 - index * 22
        lines += [TextLine(x, row_y, cell) for x, cell in zip(columns, row, strict=True)]

    lines += [
        TextLine(360, 380, "Nettobetrag:"),
        TextLine(500, 380, "1735,00"),
        TextLine(360, 358, "USt 20%:"),
        TextLine(500, 358, "340,00"),
        TextLine(360, 336, "USt 10%:"),
        TextLine(500, 336, "3,50"),
        TextLine(360, 310, "Gesamtbetrag:", bold=True),
        TextLine(500, 310, "2078,50", bold=True),
        TextLine(50, 250, "Zahlbar innerhalb von 30 Tagen ohne Abzug."),
        TextLine(50, 232, "IBAN: AT00 1111 2222 3333 4444"),
    ]
    return lines


def main() -> int:
    SAMPLES_DIR.mkdir(exist_ok=True)
    target = SAMPLES_DIR / "invoice-01.pdf"
    target.write_bytes(build_pdf(invoice_01()))
    print(f"written: {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
