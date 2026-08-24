"""Async client for the Perplexity Agent API (contract section 6).

One call is POST https://api.perplexity.ai/v1/agent with the verified body:
model, input, instructions, tools (web_search), max_output_tokens and a
response_format json_schema block.

The response carries two output items that matter:

- a search_results item with the real, resolvable URLs the agent read,
- a message item whose content entries of type output_text hold the JSON
  payload. Every such text is concatenated before parsing.

usage.cost.total_cost is the real USD cost of the call and is recorded on the
ingest run row.

The API key is read from settings at call time and is never logged, never put
in an exception message and never returned to the caller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Retry policy, contract section 6: retry twice (three attempts in total) with
# exponential backoff on timeout, 429 and 5xx. Never retry a 400.
DEFAULT_MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 30.0
RETRY_STATUS_CODES = frozenset({408, 409, 425, 429})

DEFAULT_MAX_OUTPUT_TOKENS = 4000
DEFAULT_SCHEMA_NAME = "finbit_stories"

# How much of an error body ends up in the exception message and the log.
BODY_TRUNCATE = 500

FAILED_STATUSES = frozenset({"failed", "cancelled", "canceled", "errored"})

# The API reports a run that ran into the token budget as incomplete. The body
# is still usable, it is simply cut off part way through.
INCOMPLETE_STATUSES = frozenset({"incomplete", "truncated"})

# How much of the model payload is logged at DEBUG level for diagnosis.
PAYLOAD_PREVIEW = 2000


class PerplexityError(RuntimeError):
    """An unrecoverable Perplexity Agent API failure.

    Carries the HTTP status when there was one and a truncated response body.
    The API key never appears in either.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str = "",
        attempts: int = 0,
    ) -> None:
        self.status = status
        self.body = body
        self.attempts = attempts
        detail = message
        if status is not None:
            detail = f"{detail} (HTTP {status})"
        if body:
            detail = f"{detail}: {body}"
        super().__init__(detail)


@dataclass(slots=True)
class AgentResult:
    """One parsed Agent API response."""

    output_text: str = ""
    search_results: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    status: str = ""
    response_id: str | None = None
    model: str = ""
    latency_seconds: float = 0.0
    attempts: int = 1
    max_output_tokens: int = 0

    def _tokens(self, key: str) -> int:
        try:
            return int(self.usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def total_tokens(self) -> int:
        """Total tokens billed for the call, or 0 when usage is missing."""
        return self._tokens("total_tokens")

    @property
    def input_tokens(self) -> int:
        """Prompt and search context tokens."""
        return self._tokens("input_tokens")

    @property
    def output_tokens(self) -> int:
        """Tokens the model generated."""
        return self._tokens("output_tokens")

    @property
    def truncated(self) -> bool:
        """True when the output ran into the token budget and was cut off.

        Either the API says so through an incomplete status, or the generated
        token count reached the budget that was requested.
        """
        if self.status.lower() in INCOMPLETE_STATUSES:
            return True
        return bool(self.max_output_tokens) and self.output_tokens >= self.max_output_tokens


def _truncate(text: Any, limit: int = BODY_TRUNCATE) -> str:
    """Collapse a response body to a single short line for logs and errors."""
    if text is None:
        return ""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + " ..."


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_payload(
    input_text: str,
    instructions: str,
    json_schema: dict[str, Any],
    *,
    model: str,
    schema_name: str = DEFAULT_SCHEMA_NAME,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Build the exact request body verified against the live endpoint."""
    return {
        "model": model,
        "input": input_text,
        "instructions": instructions,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": max(256, int(max_output_tokens)),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema},
        },
    }


def extract_output_text(payload: dict[str, Any]) -> str:
    """Concatenate every message content entry of type output_text.

    Falls back, in order, to any content part that carries text and to a
    flattened top level output_text field, so a small change in the response
    shape cannot silently empty the pipeline.
    """
    preferred: list[str] = []
    fallback: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str):
            fallback.append(content)
            continue
        if isinstance(content, dict):
            content = [content]
        for part in content or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if part.get("type") == "output_text":
                preferred.append(text)
            else:
                fallback.append(text)
    if preferred:
        return "".join(preferred)
    if fallback:
        return "".join(fallback)
    flat = payload.get("output_text")
    return flat if isinstance(flat, str) else ""


def extract_search_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every result from every search_results output item, in order."""
    results: list[dict[str, Any]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "search_results":
            continue
        for result in item.get("results") or []:
            if isinstance(result, dict):
                results.append(result)
    return results


def parse_agent_response(payload: dict[str, Any]) -> AgentResult:
    """Turn a raw HTTP 200 body into an AgentResult."""
    usage = payload.get("usage")
    usage_dict: dict[str, Any] = usage if isinstance(usage, dict) else {}
    cost_block = usage_dict.get("cost")
    cost = _as_float(cost_block.get("total_cost")) if isinstance(cost_block, dict) else 0.0
    return AgentResult(
        output_text=extract_output_text(payload),
        search_results=extract_search_results(payload),
        usage=usage_dict,
        cost_usd=cost,
        status=str(payload.get("status") or ""),
        response_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
        model=str(payload.get("model") or ""),
    )


def _retry_after_seconds(response: httpx.Response, fallback: float) -> float:
    """Honour a Retry-After header when the server sends a sane one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return fallback
    try:
        seconds = float(raw.strip())
    except (TypeError, ValueError):
        return fallback
    if seconds <= 0:
        return fallback
    return min(seconds, BACKOFF_MAX_SECONDS)


class PerplexityClient:
    """Reusable async client. One instance per ingestion cycle is enough."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        agent_url: str | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.require_perplexity_api_key()
        self.model = model or settings.perplexity_model
        self.agent_url = agent_url or settings.perplexity_agent_url
        self.timeout_seconds = float(
            timeout_seconds if timeout_seconds is not None else settings.perplexity_timeout_seconds
        )
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_base_seconds = max(0.0, float(backoff_base_seconds))
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> PerplexityClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool if this client owns it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds))
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        # Built fresh per request so the key is never stored on a logged object.
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def run_agent(
        self,
        input_text: str,
        instructions: str,
        json_schema: dict[str, Any],
        *,
        schema_name: str = DEFAULT_SCHEMA_NAME,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        query_key: str = "",
    ) -> AgentResult:
        """Run one agent call and return the parsed result.

        Retries twice with exponential backoff on timeout, 429 and 5xx. A 400
        or any other 4xx is raised immediately as a PerplexityError.
        """
        payload = build_payload(
            input_text,
            instructions,
            json_schema,
            model=self.model,
            schema_name=schema_name,
            max_output_tokens=max_output_tokens,
        )
        client = self._http()
        started = time.perf_counter()
        last_error: PerplexityError | None = None

        for attempt in range(1, self.max_attempts + 1):
            delay = min(
                BACKOFF_MAX_SECONDS, self.backoff_base_seconds * (2 ** (attempt - 1))
            )
            try:
                response = await client.post(
                    self.agent_url, json=payload, headers=self._headers()
                )
            except httpx.TimeoutException as exc:
                last_error = PerplexityError(
                    f"Perplexity request timed out after {self.timeout_seconds:.0f}s",
                    attempts=attempt,
                )
                logger.warning(
                    "perplexity timeout model=%s query=%s attempt=%d/%d",
                    self.model,
                    query_key or "-",
                    attempt,
                    self.max_attempts,
                )
                if attempt >= self.max_attempts:
                    raise last_error from exc
                await asyncio.sleep(delay)
                continue
            except httpx.HTTPError as exc:
                last_error = PerplexityError(
                    f"Perplexity transport error: {type(exc).__name__}",
                    attempts=attempt,
                )
                logger.warning(
                    "perplexity transport error model=%s query=%s attempt=%d/%d kind=%s",
                    self.model,
                    query_key or "-",
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                )
                if attempt >= self.max_attempts:
                    raise last_error from exc
                await asyncio.sleep(delay)
                continue

            status = response.status_code
            if status >= 500 or status in RETRY_STATUS_CODES:
                body = _truncate(response.text)
                last_error = PerplexityError(
                    "Perplexity call failed", status=status, body=body, attempts=attempt
                )
                logger.warning(
                    "perplexity retryable status model=%s query=%s attempt=%d/%d status=%d",
                    self.model,
                    query_key or "-",
                    attempt,
                    self.max_attempts,
                    status,
                )
                if attempt >= self.max_attempts:
                    raise last_error
                await asyncio.sleep(_retry_after_seconds(response, delay))
                continue

            if status >= 400:
                # 400 and the other client errors are never retried.
                raise PerplexityError(
                    "Perplexity rejected the request",
                    status=status,
                    body=_truncate(response.text),
                    attempts=attempt,
                )

            try:
                body_json = response.json()
            except ValueError as exc:
                raise PerplexityError(
                    "Perplexity returned a body that is not JSON",
                    status=status,
                    body=_truncate(response.text),
                    attempts=attempt,
                ) from exc
            if not isinstance(body_json, dict):
                raise PerplexityError(
                    "Perplexity returned a JSON body that is not an object",
                    status=status,
                    body=_truncate(response.text),
                    attempts=attempt,
                )

            result = parse_agent_response(body_json)
            result.latency_seconds = time.perf_counter() - started
            result.attempts = attempt
            result.max_output_tokens = int(payload["max_output_tokens"])
            if result.status.lower() in FAILED_STATUSES:
                raise PerplexityError(
                    f"Perplexity run ended with status {result.status}",
                    status=status,
                    body=_truncate(result.output_text),
                    attempts=attempt,
                )
            logger.info(
                "perplexity ok model=%s query=%s attempt=%d latency=%.2fs "
                "cost=%.5f usd tokens=%d in / %d out of %d results=%d status=%s",
                self.model,
                query_key or "-",
                attempt,
                result.latency_seconds,
                result.cost_usd,
                result.input_tokens,
                result.output_tokens,
                result.max_output_tokens,
                len(result.search_results),
                result.status or "unknown",
            )
            if result.truncated:
                logger.warning(
                    "perplexity output was cut off model=%s query=%s status=%s "
                    "output_tokens=%d budget=%d details=%s. Lower the stories "
                    "per query or raise the token budget.",
                    self.model,
                    query_key or "-",
                    result.status or "unknown",
                    result.output_tokens,
                    result.max_output_tokens,
                    _truncate(body_json.get("incomplete_details"), 200) or "none",
                )
            if not result.output_text.strip():
                logger.warning(
                    "perplexity returned no output text model=%s query=%s "
                    "output items=%s",
                    self.model,
                    query_key or "-",
                    [
                        item.get("type")
                        for item in body_json.get("output") or []
                        if isinstance(item, dict)
                    ],
                )
            elif logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "perplexity payload query=%s: %s",
                    query_key or "-",
                    _truncate(result.output_text, PAYLOAD_PREVIEW),
                )
            return result

        # Only reachable when max_attempts is exhausted without raising above.
        raise last_error or PerplexityError("Perplexity call failed", attempts=self.max_attempts)


async def run_agent(
    input_text: str,
    instructions: str,
    json_schema: dict[str, Any],
    *,
    schema_name: str = DEFAULT_SCHEMA_NAME,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    query_key: str = "",
) -> AgentResult:
    """One-shot convenience wrapper that opens and closes its own client."""
    async with PerplexityClient() as client:
        return await client.run_agent(
            input_text,
            instructions,
            json_schema,
            schema_name=schema_name,
            max_output_tokens=max_output_tokens,
            query_key=query_key,
        )


__all__ = [
    "AgentResult",
    "BACKOFF_BASE_SECONDS",
    "INCOMPLETE_STATUSES",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_SCHEMA_NAME",
    "PerplexityClient",
    "PerplexityError",
    "build_payload",
    "extract_output_text",
    "extract_search_results",
    "parse_agent_response",
    "run_agent",
]
