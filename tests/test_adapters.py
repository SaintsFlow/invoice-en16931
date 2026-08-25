"""The adapters, and above all the gate that stands in front of all of them."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from src.adapters.base import AdapterResult, ERPAdapter
from src.adapters.factory import AVAILABLE, create_adapter
from src.adapters.file import FileAdapter, safe_stem
from src.adapters.mock_erp import MockErpAdapter
from src.errors import AdapterFailedError, InvoiceNotValidError, UnknownAdapterError
from src.schema import Invoice
from tests.conftest import sample_invoice


def broken_invoice() -> Invoice:
    """An invoice whose gross total is nothing like the sum of its parts."""
    payload = sample_invoice().model_dump()
    payload["totals"]["gross_total"] = {"value": Decimal("999.00"), "confidence": 1.0}
    return Invoice.model_validate(payload)


class CountingAdapter(ERPAdapter):
    """Records whether delivery was actually reached."""

    name = "counting"

    def __init__(self) -> None:
        self.delivered = 0

    async def deliver(self, invoice: Invoice) -> AdapterResult:
        self.delivered += 1
        return AdapterResult(adapter=self.name, reference="nowhere")


# --- the gate ---------------------------------------------------------------------


async def test_a_broken_invoice_never_reaches_delivery() -> None:
    """The check is inside send, so no caller can go around it."""
    adapter = CountingAdapter()

    with pytest.raises(InvoiceNotValidError) as refused:
        await adapter.send(broken_invoice())

    assert adapter.delivered == 0
    assert refused.value.status_code == 422
    assert refused.value.code == "invoice_not_valid"


async def test_the_refusal_says_what_is_wrong_with_it() -> None:
    adapter = CountingAdapter()

    with pytest.raises(InvoiceNotValidError) as refused:
        await adapter.send(broken_invoice())

    rules = [violation.rule for violation in refused.value.violations]  # type: ignore[attr-defined]
    assert "BR-CO-15" in rules


async def test_a_good_invoice_goes_through() -> None:
    adapter = CountingAdapter()

    result = await adapter.send(sample_invoice())

    assert adapter.delivered == 1
    assert result.adapter == "counting"


async def test_a_new_adapter_gets_the_gate_by_existing() -> None:
    """Nothing in a subclass has to remember to check. That is the whole design."""
    assert "deliver" in ERPAdapter.__abstractmethods__
    assert "send" not in ERPAdapter.__abstractmethods__


# --- writing to disk --------------------------------------------------------------


async def test_the_file_adapter_writes_exactly_two_files(tmp_path: Path) -> None:
    result = await FileAdapter(tmp_path).send(sample_invoice())

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["R-2026-0042.json", "R-2026-0042.xml"]
    assert result.reference == str(tmp_path / "R-2026-0042.xml")


async def test_what_lands_on_disk_is_the_invoice(tmp_path: Path) -> None:
    await FileAdapter(tmp_path).send(sample_invoice())

    xml = (tmp_path / "R-2026-0042.xml").read_text(encoding="utf-8")
    flat = json.loads((tmp_path / "R-2026-0042.json").read_text(encoding="utf-8"))

    assert "<cbc:ID>R-2026-0042</cbc:ID>" in xml
    assert flat["totals_gross"] == "240.00"


async def test_the_file_adapter_makes_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "out"

    await FileAdapter(target).send(sample_invoice())

    assert (target / "R-2026-0042.xml").exists()


async def test_a_broken_invoice_leaves_no_files_behind(tmp_path: Path) -> None:
    with pytest.raises(InvoiceNotValidError):
        await FileAdapter(tmp_path).send(broken_invoice())

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("R-2026-0042", "R-2026-0042"),
        ("2026/0042", "2026-0042"),
        ("RE 2026 0042", "RE-2026-0042"),
        ("../../etc/passwd", "etc-passwd"),
        ("   ", "invoice"),
    ],
)
def test_a_file_name_never_carries_a_surprise(number: str, expected: str) -> None:
    """Invoice numbers come off a scan. A slash in one writes somewhere else."""
    assert safe_stem(number) == expected


def test_the_output_directory_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "chosen"))

    assert FileAdapter().output_dir == tmp_path / "chosen"


# --- posting to a receiver --------------------------------------------------------


def receiver(status: int, seen: list[httpx.Request] | None = None) -> MockErpAdapter:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"ok": status < 400})

    return MockErpAdapter("https://erp.example/invoices", transport=httpx.MockTransport(handle))


async def test_the_receiver_gets_both_renderings() -> None:
    seen: list[httpx.Request] = []

    result = await receiver(201, seen).send(sample_invoice())

    body = json.loads(seen[0].content)
    assert body["invoice_number"] == "R-2026-0042"
    assert body["ubl_xml"].startswith("<?xml")
    assert body["flat_json"]["totals_gross"] == "240.00"
    assert result.detail == "HTTP 201"


async def test_a_receiver_that_answers_500_is_an_error_not_a_shrug() -> None:
    """Returning happily here would turn a delivery failure into silent data loss."""
    with pytest.raises(AdapterFailedError) as failed:
        await receiver(500).send(sample_invoice())

    assert failed.value.status_code == 502
    assert "500" in failed.value.message


@pytest.mark.parametrize("status", [400, 401, 404, 409, 500, 503])
async def test_every_refusal_status_is_an_error(status: int) -> None:
    with pytest.raises(AdapterFailedError):
        await receiver(status).send(sample_invoice())


async def test_a_receiver_that_cannot_be_reached_is_an_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    adapter = MockErpAdapter("https://erp.example/x", transport=httpx.MockTransport(refuse))

    with pytest.raises(AdapterFailedError) as failed:
        await adapter.send(sample_invoice())

    assert "no route to host" in failed.value.message


async def test_a_broken_invoice_is_never_posted() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(InvoiceNotValidError):
        await receiver(200, seen).send(broken_invoice())

    assert seen == []


def test_a_receiver_with_no_url_is_refused_at_build_time() -> None:
    with pytest.raises(UnknownAdapterError):
        MockErpAdapter("   ")


# --- choosing one -----------------------------------------------------------------


def test_the_default_adapter_writes_files() -> None:
    assert create_adapter().name == "file"


def test_the_adapter_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_ADAPTER", "mock_erp")
    monkeypatch.setenv("ERP_URL", "https://erp.example/invoices")

    adapter = create_adapter()
    assert adapter.name == "mock_erp"
    assert isinstance(adapter, MockErpAdapter)
    assert adapter.url == "https://erp.example/invoices"


def test_an_empty_variable_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_ADAPTER", "")

    assert create_adapter().name == "file"


def test_a_typo_in_the_adapter_name_says_what_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_ADAPTER", "sap")

    with pytest.raises(UnknownAdapterError) as unknown:
        create_adapter()

    for name in AVAILABLE:
        assert name in unknown.value.message
