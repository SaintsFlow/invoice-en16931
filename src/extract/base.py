"""What every language model provider has to offer. Providers differ, the call does not."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]
"""Who is speaking. The retry needs "assistant" to quote the answer we refused."""


class Message(BaseModel):
    """One turn of the conversation with the model."""

    role: Role
    content: str


class LlmProvider(ABC):
    """The contract the extractor depends on.

    The provider carries messages there and the answer back. It knows nothing
    about invoices: parsing the answer and deciding whether it is good enough
    happens in one place, the extractor.
    """

    name: str = "base"

    @abstractmethod
    async def complete(self, messages: Sequence[Message], schema: Mapping[str, Any]) -> str:
        """Ask the model and return the raw answer text.

        The schema describes the JSON we want back. It is a request, not a
        guarantee: whether the answer fits is checked by the caller.
        """
