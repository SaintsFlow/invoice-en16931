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

**Validation is not optional, and it does not throw anything away.** Every rule runs on
every invoice, and a failure names the rule, the business term, what was expected and
what was actually there. The invoice comes back whole alongside the violations: the one
that does not add up is exactly the one somebody has to look at, and handing them
nothing to correct helps no one. A wrong invoice total is worse than no invoice at all.

**A cent is rounding, two cents is an error.** Real invoices are written with rounding
in them. The threshold sits in a single constant so it can be argued about.

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

## What you get back

`POST /extract` answers with the invoice, whether it passed the checks or not:

```json
{
  "filename": "invoice-01.pdf",
  "reading": { "engine": "tesseract", "pages": 1, "text_lines": 21 },
  "valid": false,
  "violations": [
    {
      "rule": "BR-CO-17",
      "bt": "BT-117",
      "field": "vat_breakdown[0].tax_amount",
      "message": "vat_breakdown[0].tax_amount is off from 1200.00 at 20% by 100.00",
      "expected": "240.00",
      "actual": "340.00"
    }
  ],
  "invoice": { "...": "every field that was read, each with a confidence" }
}
```

That example is real. A model reading the sample invoice claimed a taxable base of
1200.00 while charging VAT on 1700.00, which no arithmetic produces. Rules named
`BR-something` are quoted from the Schematron the European Commission publishes for
EN 16931. Rules prefixed `OWN-` are this project's, for things the standard defines
but does not check, such as a line total matching its own quantity and price.

## Output and delivery

A checked invoice is rendered two ways. UBL 2.1 XML, which is what Peppol carries, and
a flat JSON for anything that does not speak XML. Both come from the same invoice, and
a test pairs their values field by field so they cannot drift apart.

The XML is validated in the test suite against the OASIS UBL 2.1 schemas, which live in
`schemas/ubl-2.1/`. XML that merely looks like UBL is worth nothing: the receiver
validates, and a document that fails there fails after it has left.

Delivery sits behind `ERPAdapter`, chosen with `ERP_ADAPTER`:

| Adapter | What it does |
|---|---|
| `file` | writes `<number>.xml` and `<number>.json` into `OUTPUT_DIR` |
| `mock_erp` | posts both renderings to `ERP_URL` and insists on being told they arrived |

**An invoice that fails the checks is never delivered.** The check sits inside
`ERPAdapter.send`, not in the code that calls it, so there is no way in that skips it
and a new adapter gets the protection by existing. A receiver that answers 500 has not
taken the invoice, and saying otherwise would turn a delivery problem into a silent
loss that surfaces weeks later.

## What is not here yet

- Peppol transport
- credit notes and corrections
- allowances, charges and payment means, so an invoice that has any is not represented
- a wider set of sample invoices

## License

MIT
