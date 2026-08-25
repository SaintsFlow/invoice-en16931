"""The OpenAI provider. The transport is handed in, so no test can reach the network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.errors import LlmConfigError, LlmRequestError
from src.extract.base import Message
from src.extract.openai import DEFAULT_MODEL, OpenAIProvider

MESSAGES = [Message(role="system", content="read the invoice"), Message(role="user", content="R1")]
SCHEMA: dict[str, Any] = {"type": "object", "properties": {"number": {"type": "string"}}}


def envelope(content: str) -> dict[str, Any]:
    """What the chat completions endpoint wraps an answer in."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def provider_answering(
    response: httpx.Response, seen: list[httpx.Request] | None = None, **options: Any
) -> OpenAIProvider:
    """A provider whose only reachable endpoint is the one built here."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return response

    return OpenAIProvider(
        api_key="test-key",
        base_url="https://models.example/v1",
        transport=httpx.MockTransport(handle),
        **options,
    )


async def test_the_request_carries_the_model_the_messages_and_the_schema() -> None:
    seen: list[httpx.Request] = []
    provider = provider_answering(
        httpx.Response(200, json=envelope('{"number": "R1"}')), seen, model="gpt-4o-mini"
    )

    await provider.complete(MESSAGES, SCHEMA)

    request = seen[0]
    assert str(request.url) == "https://models.example/v1/chat/completions"
    assert request.headers["Authorization"].startswith("Bearer ")
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.0
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA


async def test_the_answer_is_taken_out_of_the_envelope() -> None:
    provider = provider_answering(httpx.Response(200, json=envelope('{"number": "R1"}')))

    answer = await provider.complete(MESSAGES, SCHEMA)

    assert answer == '{"number": "R1"}'


async def test_the_model_name_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")

    assert OpenAIProvider.from_env().model == "gpt-4.1"


async def test_without_a_model_name_a_known_default_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert OpenAIProvider.from_env().model == DEFAULT_MODEL


async def test_no_key_means_no_provider() -> None:
    """The suite runs without a key, so this is also the guard against a real call."""
    with pytest.raises(LlmConfigError) as missing:
        OpenAIProvider.from_env()

    assert "OPENAI_API_KEY" in missing.value.message


async def test_a_blank_key_counts_as_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    with pytest.raises(LlmConfigError):
        OpenAIProvider.from_env()


async def test_a_nonsense_timeout_falls_back_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "soon")

    assert OpenAIProvider.from_env().timeout == 60.0


async def test_an_error_status_becomes_our_own_error() -> None:
    provider = provider_answering(httpx.Response(429, json={"error": "slow down"}))

    with pytest.raises(LlmRequestError) as failed:
        await provider.complete(MESSAGES, SCHEMA)

    assert failed.value.status_code == 502
    assert "429" in failed.value.message


async def test_a_network_failure_becomes_our_own_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://models.example/v1",
        transport=httpx.MockTransport(refuse),
    )

    with pytest.raises(LlmRequestError) as failed:
        await provider.complete(MESSAGES, SCHEMA)

    assert "no route to host" in failed.value.message


async def test_an_envelope_of_an_unexpected_shape_becomes_our_own_error() -> None:
    provider = provider_answering(httpx.Response(200, json={"choices": []}))

    with pytest.raises(LlmRequestError):
        await provider.complete(MESSAGES, SCHEMA)


async def test_an_answer_that_is_not_json_becomes_our_own_error() -> None:
    provider = provider_answering(httpx.Response(200, text="<html>gateway</html>"))

    with pytest.raises(LlmRequestError):
        await provider.complete(MESSAGES, SCHEMA)
