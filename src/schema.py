"""The invoice model: EN 16931 core plus the Peppol BIS Billing 3.0 profile fields.

Every business term keeps its BT code in the field metadata, so a field can be
checked against the standard without guessing, and an error can name the term a
human will look up.

Two rules hold everywhere in this file:

* Money is Decimal. A float cannot hold cents exactly, and an invoice that is off
  by a cent is a wrong invoice. Passing a float into a money field is an error,
  not something to round away.
* Anything the model extracts is wrapped in Field, which carries the value and how
  sure we are about it. A human reviewing the result needs to know where to look.

The model describes the shape of an invoice, not whether it is a legal one. Rules
like "a Peppol invoice must carry a buyer reference" belong to the validation step,
so fields the standard requires are optional here when a PDF may simply not show
them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, get_args, get_origin

import pydantic
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError
from pydantic.fields import FieldInfo

# Peppol BIS Billing 3.0 is EN 16931 expressed in UBL 2.1, which is what the service
# renders. Austria accepts it for B2G next to the national ebInterface format, and it
# reaches German buyers too. Both values are case sensitive and go out as written.
PEPPOL_CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
PEPPOL_PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"


def _reject_float(value: object) -> object:
    """Stop a float before pydantic can quietly turn it into a Decimal."""
    if isinstance(value, float):
        raise ValueError(
            "money must not come from a float, it loses cents: pass a Decimal or a string"
        )
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]
"""A monetary amount. Accepts Decimal, int and str. A float is refused."""

# Constraints go on the value type, not on the Field wrapper around it: a pattern put
# on the wrapper would be checked against the wrapper model and fail to apply.
CountryCode = Annotated[str, pydantic.StringConstraints(pattern=r"^[A-Z]{2}$")]
CurrencyCode = Annotated[str, pydantic.StringConstraints(pattern=r"^[A-Z]{3}$")]


class StrictModel(BaseModel):
    """Base for every model here. An unknown key is a typo, not a field to keep."""

    model_config = ConfigDict(extra="forbid")


class Field[T](StrictModel):
    """One extracted value together with how sure we are about it.

    Confidence runs from 0 to 1. OCR confidence in src/ocr/base.py runs from 0 to 100
    because that is the scale tesseract reports. The two are different measurements
    and are kept on different scales on purpose, so nobody averages them by accident.
    """

    value: T
    confidence: float = pydantic.Field(default=1.0, ge=0.0, le=1.0)


def confidence_of(field: Field[Any] | None) -> float:
    """How sure we are about one field.

    A field that is not there is a field nobody could read, and that counts as
    zero. Without this the caller has to spell out the None case every time it
    wants to show a human which values to look at.
    """
    return 0.0 if field is None else field.confidence


class PostalAddress(StrictModel):
    """A postal address. BT codes differ by role: seller first, buyer second."""

    line_one: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-35", "BT-50"]}
    )
    line_two: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-36", "BT-51"]}
    )
    city: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-37", "BT-52"]}
    )
    post_code: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-38", "BT-53"]}
    )
    country_subdivision: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-39", "BT-54"]}
    )
    # The one part of an address the standard insists on. Two letters, ISO 3166-1.
    country_code: Field[CountryCode] = pydantic.Field(json_schema_extra={"bt": ["BT-40", "BT-55"]})


class Party(StrictModel):
    """A seller or a buyer. BT codes differ by role: seller first, buyer second."""

    name: Field[str] = pydantic.Field(json_schema_extra={"bt": ["BT-27", "BT-44"]})
    vat_id: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-31", "BT-48"]}
    )
    address: PostalAddress
    # Peppol routes on the electronic address, and the scheme says how to read it
    # (0088 is a GLN, 9915 an Austrian VAT number). A PDF rarely prints either, so
    # both stay optional and the validation step decides whether that is a problem.
    endpoint_id: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-34", "BT-49"]}
    )
    endpoint_scheme_id: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": ["BT-34-1", "BT-49-1"]}
    )


class InvoiceLine(StrictModel):
    """One position of the invoice."""

    identifier: Field[str] | None = pydantic.Field(default=None, json_schema_extra={"bt": "BT-126"})
    name: Field[str] = pydantic.Field(json_schema_extra={"bt": "BT-153"})
    quantity: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-129"})
    # UN/ECE Recommendation 20 code. C62 means "one", the fallback for countable things.
    quantity_unit_code: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": "BT-130"}
    )
    net_price: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-146"})
    net_amount: Field[Money] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": "BT-131"}
    )
    vat_category_code: Field[str] = pydantic.Field(json_schema_extra={"bt": "BT-151"})
    vat_rate: Field[Money] | None = pydantic.Field(default=None, json_schema_extra={"bt": "BT-152"})


class VatBreakdown(StrictModel):
    """VAT for one category and rate. An invoice carries one entry per rate it uses."""

    category_code: Field[str] = pydantic.Field(json_schema_extra={"bt": "BT-118"})
    # A percentage, not money, but the same exactness argument applies: 19.6 as a float
    # is not 19.6, and the tax it produces is off.
    rate: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-119"})
    taxable_amount: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-116"})
    tax_amount: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-117"})


class Totals(StrictModel):
    """The document totals. Whether they add up is checked in the validation step."""

    line_net_total: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-106"})
    net_total: Field[Money] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": "BT-109"}
    )
    vat_total: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-110"})
    gross_total: Field[Money] = pydantic.Field(json_schema_extra={"bt": "BT-112"})
    amount_due: Field[Money] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": "BT-115"}
    )


class Invoice(StrictModel):
    """A whole invoice, as far as it could be read out of the PDF."""

    # Profile identifiers. They say which specification the document follows, so they
    # are constants of the profile rather than something to read off the page.
    customization_id: str = pydantic.Field(
        default=PEPPOL_CUSTOMIZATION_ID, json_schema_extra={"bt": "BT-24"}
    )
    profile_id: str = pydantic.Field(default=PEPPOL_PROFILE_ID, json_schema_extra={"bt": "BT-23"})

    number: Field[str] = pydantic.Field(json_schema_extra={"bt": "BT-1"})
    issue_date: Field[date] = pydantic.Field(json_schema_extra={"bt": "BT-2"})
    # UNTDID 1001 code. 380 is a commercial invoice, 381 a credit note.
    type_code: Field[str] | None = pydantic.Field(default=None, json_schema_extra={"bt": "BT-3"})
    currency: Field[CurrencyCode] = pydantic.Field(json_schema_extra={"bt": "BT-5"})
    due_date: Field[date] | None = pydantic.Field(default=None, json_schema_extra={"bt": "BT-9"})
    # Peppol wants this one, a PDF often does not print it. Validation decides.
    buyer_reference: Field[str] | None = pydantic.Field(
        default=None, json_schema_extra={"bt": "BT-10"}
    )

    seller: Party
    buyer: Party
    lines: list[InvoiceLine] = pydantic.Field(min_length=1)
    vat_breakdown: list[VatBreakdown] = pydantic.Field(min_length=1)
    totals: Totals


# Fields whose BT code depends on whether they sit under the seller or the buyer.
_ROLES = ("seller", "buyer")


def _bt_of(field: FieldInfo, role: str | None) -> str | None:
    """Read the BT code out of the field metadata, picking the right one by role."""
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return None
    code = extra.get("bt")
    if isinstance(code, str):
        return code
    if isinstance(code, list):
        if role in _ROLES:
            return str(code[_ROLES.index(role)])
        return " / ".join(f"{c} {r}" for c, r in zip(code, _ROLES, strict=False))
    return None


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """Find the model an annotation points at, through list[...], Field[...] and None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) is None:
        return None
    for arg in get_args(annotation):
        found = _model_of(arg)
        if found is not None:
            return found
    return None


def _bt_at(model: type[BaseModel], loc: tuple[int | str, ...]) -> str | None:
    """Follow an error location down the model tree and keep the deepest BT code seen."""
    current: type[BaseModel] | None = model
    role: str | None = None
    code: str | None = None
    for part in loc:
        if current is None or not isinstance(part, str):
            continue
        field = current.model_fields.get(part)
        if field is None:
            continue
        if part in _ROLES:
            role = part
        found = _bt_of(field, role)
        if found is not None:
            code = found
        current = _model_of(field.annotation)
    return code


def describe_errors(model: type[BaseModel], error: ValidationError) -> list[str]:
    """Turn a validation failure into lines a human can act on.

    Pydantic names the field but knows nothing about BT codes, and the BT code is what
    someone checking against the standard needs. One line per problem.
    """
    lines: list[str] = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "invoice"
        code = _bt_at(model, item["loc"])
        label = f"{where} ({code})" if code else where
        lines.append(f"{label}: {item['msg']}")
    return lines
