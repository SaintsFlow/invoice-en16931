"""Talking to OpenAI over plain HTTP.

The project stack fixes httpx for HTTP, so the request is built here by hand
instead of pulling in a vendor SDK for one POST. It also keeps the tests honest:
they hand in a transport and the network stays out of reach.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, Final

import httpx

from src.errors import LlmConfigError, LlmRequestError
from src.extract.base import LlmProvider, Message
from src.logs import get_logger

log = get_logger()

DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MODEL: Final = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

# Extraction is reading, not writing. The least inventive setting is the right one.
TEMPERATURE: Final = 0.0

# The name travels with the schema and shows up in provider side errors.
SCHEMA_NAME: Final = "invoice"


class OpenAIProvider(LlmProvider):
    """Chat completions with a JSON schema attached to the request.

    The schema goes out with `strict` off. Strict mode accepts a narrow subset of
    JSON Schema, and the invoice model steps outside it in several places at once
    (patterns on country and currency codes, bounds on confidence, a date format).
    Cleaning the schema down to that subset would mean keeping a second description
    of the model in sync with the first. So the schema goes as it is, and the
    guarantee comes from validating the answer, which is needed either way.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise LlmConfigError("OPENAI_API_KEY is empty, the model cannot be called")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    @property
    def model(self) -> str:
        """Which model this provider talks to. Worth reporting next to a result."""
        return self._model

    @property
    def timeout(self) -> float:
        """How long one call may take, in seconds."""
        return self._timeout

    @classmethod
    def from_env(cls) -> OpenAIProvider:
        """Build the provider from the environment.

        Missing configuration stops us here, with a message naming the variable,
        rather than as a puzzling failure on the first upload of the day.
        """
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key.strip():
            raise LlmConfigError("OPENAI_API_KEY is not set, extraction needs a key")
        return cls(
            api_key=key,
            model=os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
            base_url=os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
            timeout=_timeout_from_env(),
        )

    async def complete(self, messages: Sequence[Message], schema: Mapping[str, Any]) -> str:
        body = self._body(messages, schema)
        # A client per call costs one handshake against a call that takes seconds,
        # and it saves the caller from owning a connection pool it never asked for.
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except httpx.HTTPError as failure:
                raise LlmRequestError(f"could not reach the model: {failure}") from failure

        if response.status_code >= 400:
            log.warning("llm_request_failed", status=response.status_code, model=self._model)
            raise LlmRequestError(f"the model answered with HTTP {response.status_code}")

        return _answer_of(response)

    def _body(self, messages: Sequence[Message], schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "model": self._model,
            "temperature": TEMPERATURE,
            "messages": [message.model_dump() for message in messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "strict": False,
                    "schema": dict(schema),
                },
            },
        }


def _timeout_from_env() -> float:
    """Read the timeout, and treat nonsense as "not set" instead of crashing."""
    raw = os.environ.get("OPENAI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        log.warning("llm_timeout_ignored", value=raw)
        return DEFAULT_TIMEOUT_SECONDS
    return seconds if seconds > 0 else DEFAULT_TIMEOUT_SECONDS


def _answer_of(response: httpx.Response) -> str:
    """Pull the answer text out of the envelope, or say what was wrong with it."""
    try:
        payload = response.json()
    except ValueError as broken:
        raise LlmRequestError("the model answered with something that is not JSON") from broken

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as odd:
        raise LlmRequestError(f"the model answer has an unexpected shape: {odd}") from odd

    if not isinstance(content, str):
        raise LlmRequestError("the model answer carries no text")
    return content
