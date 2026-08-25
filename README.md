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

**The target profile is Peppol BIS Billing 3.0.** It is EN 16931 written in UBL 2.1,
which is the format this service already produces. Austria accepts it for public sector
invoicing next to the national ebInterface format, and it reaches German buyers too.
The few fields the profile adds on top of the core, such as the specification and
process identifiers and the electronic addresses of both parties, are part of the model
from the start, because adding them later would break every consumer of the schema.

**A value that was not seen comes back empty.** The prompt lives in `prompts/extract.md`,
not in the code, and its first rule is that a value which is not visible in the text is
returned as null. Never a guess, never a number worked out from the other numbers. A null
costs a reviewer ten seconds; an invented amount goes into accounting and stays there.
An answer that does not fit the schema buys exactly one retry, with the validation error
quoted back to the model, and then fails with the field name and its BT code.

**Money is a decimal, never a float.** A float cannot hold cents exactly, and an invoice
that is off by a cent is a wrong invoice. Passing a float into a money field raises a
validation error instead of being rounded away. In JSON, amounts travel as strings for
the same reason.

## What is not here yet

- `POST /extract` still answers with what OCR saw, not with the invoice. Extraction
  works and is covered by tests, but it is wired into the response together with the
  XML and JSON output stage
- validation of the extracted fields, so nothing is checked against the arithmetic yet
- Peppol transport
- credit notes and corrections
- a wider set of sample invoices

## License

MIT
