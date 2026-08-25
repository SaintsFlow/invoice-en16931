"""Where a finished invoice goes, and the one gate every route has to pass.

The gate is here, in `send`, not in whoever calls it. An adapter that could be handed
an invoice which does not add up would eventually be handed one: a new caller, a retry
path, a script somebody wrote on a Friday. Putting the check in the base class means
there is no way in that skips it, and a new adapter gets the protection by existing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from src.errors import InvoiceNotValidError
from src.logs import get_logger
from src.schema import Invoice
from src.validate import check

log = get_logger()


class AdapterResult(BaseModel):
    """What happened when the invoice was handed on."""

    adapter: str
    reference: str
    """Where it went: a path, a URL, an id the receiver gave back."""

    detail: str = ""


class ERPAdapter(ABC):
    """One way of delivering an invoice. File today, a real ERP later."""

    name: str = "base"

    async def send(self, invoice: Invoice) -> AdapterResult:
        """Check the invoice, then deliver it.

        Do not override this. The work goes in `deliver`, which only ever runs on
        an invoice that passed every rule.
        """
        report = check(invoice)
        if not report.valid:
            log.warning(
                "delivery_refused",
                adapter=self.name,
                violations=[violation.rule for violation in report.violations],
            )
            raise InvoiceNotValidError(
                f"the invoice breaks {len(report.violations)} rules and was not sent",
                report.violations,
            )

        result = await self.deliver(invoice)
        log.info("invoice_delivered", adapter=self.name, reference=result.reference)
        return result

    @abstractmethod
    async def deliver(self, invoice: Invoice) -> AdapterResult:
        """Actually hand the invoice over. Only called on a valid one."""
