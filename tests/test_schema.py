"""The invoice model: what it accepts, what it refuses, and what it says when it refuses."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from src.schema import (
    PEPPOL_CUSTOMIZATION_ID,
    PEPPOL_PROFILE_ID,
    CurrencyCode,
    Field,
    Invoice,
    Money,
    describe_errors,
)
from tests.conftest import sample_invoice


def without(data: dict[str, object], key: str) -> dict[str, object]:
    """The same payload with one key taken out."""
    return {name: value for name, value in data.items() if name != key}


def test_the_model_survives_a_round_trip() -> None:
    invoice = sample_invoice()

    again = Invoice.model_validate(invoice.model_dump(mode="json"))

    assert again == invoice


def test_money_stays_exact_through_a_round_trip() -> None:
    invoice = sample_invoice()

    dumped = invoice.model_dump(mode="json")

    # A string, not a JSON number. That is what keeps the cents.
    assert dumped["totals"]["gross_total"]["value"] == "240.00"
    assert Invoice.model_validate(dumped).totals.gross_total.value == Decimal("240.00")


def test_a_float_is_refused_as_money() -> None:
    with pytest.raises(ValidationError) as caught:
        Field[Money](value=12.34)

    assert "float" in str(caught.value)


def test_decimal_and_string_are_accepted_as_money() -> None:
    assert Field[Money](value=Decimal("12.34")).value == Decimal("12.34")
    assert Field[Money](value="12.34").value == Decimal("12.34")
    assert Field[Money](value=12).value == Decimal("12")


def test_a_missing_field_is_named_with_its_bt_code() -> None:
    payload = without(sample_invoice().model_dump(mode="json"), "number")

    with pytest.raises(ValidationError) as caught:
        Invoice.model_validate(payload)

    problems = describe_errors(Invoice, caught.value)
    assert problems == ["number (BT-1): Field required"]


def test_the_bt_code_of_an_address_follows_the_role() -> None:
    """The same address field has one BT code under the seller and another under the buyer."""
    codes = []
    for role in ("seller", "buyer"):
        payload = sample_invoice().model_dump(mode="json")
        party = dict(payload[role])
        party["address"] = without(party["address"], "country_code")
        payload[role] = party

        with pytest.raises(ValidationError) as caught:
            Invoice.model_validate(payload)
        codes.append(describe_errors(Invoice, caught.value)[0])

    assert codes == [
        "seller.address.country_code (BT-40): Field required",
        "buyer.address.country_code (BT-55): Field required",
    ]


def test_the_profile_is_peppol_bis_billing() -> None:
    invoice = sample_invoice()

    assert invoice.customization_id == PEPPOL_CUSTOMIZATION_ID
    assert invoice.profile_id == PEPPOL_PROFILE_ID
    assert PEPPOL_CUSTOMIZATION_ID.endswith("poacc:billing:3.0")


def test_an_unknown_key_is_refused() -> None:
    payload = sample_invoice().model_dump(mode="json")
    payload["invoice_no"] = {"value": "R-1", "confidence": 1.0}

    with pytest.raises(ValidationError):
        Invoice.model_validate(payload)


def test_an_invoice_needs_at_least_one_line() -> None:
    payload = sample_invoice().model_dump(mode="json")
    payload["lines"] = []

    with pytest.raises(ValidationError):
        Invoice.model_validate(payload)


def test_a_currency_has_to_look_like_a_currency() -> None:
    payload = sample_invoice().model_dump(mode="json")
    payload["currency"] = {"value": "eur", "confidence": 1.0}

    with pytest.raises(ValidationError) as caught:
        Invoice.model_validate(payload)

    assert "BT-5" in describe_errors(Invoice, caught.value)[0]


def test_confidence_stays_between_zero_and_one() -> None:
    assert Field[str](value="x").confidence == 1.0

    with pytest.raises(ValidationError):
        Field[str](value="x", confidence=1.5)


def test_a_date_comes_back_as_a_date() -> None:
    invoice = Invoice.model_validate(sample_invoice().model_dump(mode="json"))

    assert invoice.issue_date.value == date(2026, 8, 25)


def models_of(annotation: object) -> list[type[BaseModel]]:
    """Every model class hiding inside an annotation: list[X], Field[X], X | None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        found.extend(models_of(arg))
    return found


def walk_fields(model: type[BaseModel], seen: set[type[BaseModel]]) -> Iterator[tuple[str, object]]:
    """Every field of the model and of everything it holds, name and annotation."""
    if model in seen:
        return
    seen.add(model)
    for name, field in model.model_fields.items():
        yield name, field.annotation
        for nested in models_of(field.annotation):
            yield from walk_fields(nested, seen)


def test_the_only_float_in_the_schema_is_confidence() -> None:
    """No money is a float. Confidence is, and it is the one thing that may be."""
    floats = [name for name, annotation in walk_fields(Invoice, set()) if annotation is float]

    assert set(floats) == {"confidence"}


def test_currency_code_is_the_constrained_string() -> None:
    assert Field[CurrencyCode](value="EUR").value == "EUR"

    with pytest.raises(ValidationError):
        Field[CurrencyCode](value="EURO")


def test_no_pattern_in_the_schema_uses_a_lookahead() -> None:
    """A lookahead cannot become a grammar, and a model server then refuses everything.

    Measured on ollama with qwen3:8b: the regex pydantic generates for a Decimal
    carries a negative lookahead, and the whole request comes back as "failed to
    parse grammar". Money is described by hand for that reason, so this guards the
    rest of the model against picking up the same problem.
    """
    schema = json.dumps(Invoice.model_json_schema())
    patterns = re.findall(r'"pattern":\s*"((?:[^"\\]|\\.)*)"', schema)

    assert patterns, "the schema has no patterns at all, this test is checking nothing"
    assert [p for p in patterns if "(?!" in p or "(?=" in p] == []


def test_money_is_described_as_a_string() -> None:
    """The schema has to say what the prompt says, or the model gets two answers."""
    value = Field[Money].model_json_schema()["properties"]["value"]

    assert value["type"] == "string"
    assert re.fullmatch(value["pattern"], "240.00")
    assert re.fullmatch(value["pattern"], "-12")
    assert not re.fullmatch(value["pattern"], "240,00")
    assert not re.fullmatch(value["pattern"], "EUR 240.00")
