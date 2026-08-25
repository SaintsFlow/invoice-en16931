# invoice-en16931

Takes a PDF invoice, reads it with OCR, extracts the fields with an LLM, and returns a
structured invoice that follows the European standard EN 16931. Output is available as
UBL XML and as JSON.

**Status:** early. The pipeline below is the plan. Not all stages are implemented.

## Why

Electronic invoicing is mandatory for public sector suppliers in Austria and in most of
the EU, and EN 16931 is the semantic model behind it. At the same time a large share of
invoices still arrives as a PDF or a scan. Somebody has to turn one into the other, and
right now that somebody is usually a person retyping numbers.

OCR alone is not enough, because layouts differ between suppliers and a fixed template
breaks on the first new vendor. An LLM handles the layout variation, but it also
invents values when it is unsure, so every extracted field is checked against the
standard before anything is written out.

## Pipeline

```
PDF  ->  OCR  ->  LLM extraction  ->  validation  ->  UBL XML + JSON  ->  ERP adapter
```

1. **OCR.** PaddleOCR or Tesseract, with layout information kept so table rows stay together.
2. **Extraction.** The model fills a fixed schema: seller, buyer, invoice number, dates, currency, line items, tax breakdown, totals.
3. **Validation.** Required EN 16931 fields must be present, line totals must add up to the invoice total, tax amounts must match the rates, dates must parse.
4. **Output.** UBL 2.1 XML plus a flat JSON version for anything that does not speak XML.
5. **Adapter.** A small interface so the result can be written somewhere. Two implementations ship with the project: write to a file, and post to a mock ERP.

## Quick start

```bash
cp .env.example .env    # OCR engine and LLM API key
docker compose up
curl -F file=@samples/invoice-01.pdf http://localhost:8080/extract
```

## Design decisions

**The ERP sits behind an adapter.** The interesting part is turning a document into
validated structured data. Which system receives it is a detail, so it lives behind
`ERPAdapter` and can be swapped.

**Validation is not optional.** Anything the model produces that fails the arithmetic or
the required field check is returned as an error with the field name, not silently
passed on. A wrong invoice total is worse than no invoice at all.

**Confidence is reported per field.** The response says which fields came out clean and
which need a human to look at them.

## What is not here yet

- Peppol transport
- credit notes and corrections
- a wider set of sample invoices

## License

MIT
