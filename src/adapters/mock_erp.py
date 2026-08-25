"""Posting the invoice to an HTTP receiver, standing in for a real ERP.

The point of this one is the failure path. A receiver that answers 500 has not taken
the invoice, and an adapter that returns happily anyway turns a delivery problem into
a silent data loss that surfaces weeks later when somebody asks where an invoice went.
So a bad status becomes an error, loudly.
"""

from __future__ import annotations

import os
from typing import Final

import httpx

from src.adapters.base import AdapterResult, ERPAdapter
from src.errors import AdapterFailedError, UnknownAdapterError
from src.logs import get_logger
from src.render import json_out, ubl
from src.schema import Invoice

log = get_logger()

DEFAULT_TIMEOUT_SECONDS: Final = 30.0


class MockErpAdapter(ERPAdapter):
    """Sends both renderings as one JSON body and insists on being told it arrived."""

    name = "mock_erp"

    def __init__(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url.strip():
            raise UnknownAdapterError("ERP_URL is empty, the mock adapter has nowhere to post")
        self._url = url
        self._timeout = timeout
        self._transport = transport

    @property
    def url(self) -> str:
        return self._url

    async def deliver(self, invoice: Invoice) -> AdapterResult:
        body = {
            "invoice_number": invoice.number.value,
            "ubl_xml": ubl.render(invoice),
            "flat_json": json_out.render(invoice),
        }

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.post(self._url, json=body)
            except httpx.HTTPError as unreachable:
                raise AdapterFailedError(
                    f"could not reach the receiver at {self._url}: {unreachable}"
                ) from unreachable

        if response.status_code >= 400:
            log.warning(
                "erp_refused_invoice",
                status=response.status_code,
                url=self._url,
                invoice=invoice.number.value,
            )
            raise AdapterFailedError(
                f"the receiver answered HTTP {response.status_code} and did not take the invoice"
            )

        log.info("erp_accepted_invoice", status=response.status_code, url=self._url)
        return AdapterResult(
            adapter=self.name,
            reference=self._url,
            detail=f"HTTP {response.status_code}",
        )


def url_from_env() -> str:
    return os.environ.get("ERP_URL", "").strip()
