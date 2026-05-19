"""
Async LLM client — thin wrapper around the ``openai`` SDK.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_temperature(model: str, requested: float) -> float:
    normalized = str(model or "").strip().lower()
    if normalized in {"kimi-k2.5", "ccr/kimi-k2.5"}:
        return 1
    return requested


class AsyncLLMClient:
    """OpenAI-compatible async chat client.

    All calls are dispatched to a background thread so the event loop stays
    free while the synchronous ``openai`` SDK performs the HTTP round-trip.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_tokens: int = 100000,
        temperature: float = 0.4,
    ) -> None:
        import httpx
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=httpx.Timeout(600.0, connect=30.0),  # 10 min max per request
        )
        self.model = model or os.environ.get("EVOLVE_MODEL", "gpt-4o")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._semaphore = asyncio.Semaphore(3)

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Send a chat completion request and return the assistant content."""
        async with self._semaphore:
            requested_temperature = kwargs.pop("temperature", self.temperature)
            merged = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": kwargs.pop("max_tokens", self.max_tokens),
                "temperature": _normalize_temperature(self.model, requested_temperature),
                **kwargs,
            }

            # --- LLM call logging: request ---
            prompt_len = sum(len(m.get("content", "")) for m in messages)
            logger.info(
                "[LLM] >>> REQUEST model=%s prompt_len=%d temperature=%s max_tokens=%s",
                merged.get("model"), prompt_len, merged.get("temperature"), merged.get("max_completion_tokens"),
            )
            t0 = time.monotonic()

            max_retries = 6
            for attempt in range(max_retries):
                try:
                    # Rate limit delay between LLM calls
                    delay = float(os.environ.get("LLM_CALL_DELAY", "0"))
                    if delay > 0:
                        await asyncio.sleep(delay)
                    resp = await asyncio.to_thread(
                        self._client.chat.completions.create,
                        **merged,
                    )
                    elapsed = time.monotonic() - t0
                    content = resp.choices[0].message.content or ""
                    # --- LLM call logging: response ---
                    usage = getattr(resp, "usage", None)
                    logger.info(
                        "[LLM] <<< RESPONSE model=%s status=ok elapsed=%.1fs resp_len=%d prompt_tokens=%s completion_tokens=%s",
                        merged.get("model"), elapsed, len(content),
                        getattr(usage, "prompt_tokens", "?") if usage else "?",
                        getattr(usage, "completion_tokens", "?") if usage else "?",
                    )
                    return content
                except Exception as exc:
                    elapsed = time.monotonic() - t0
                    body_text = getattr(getattr(exc, "response", None), "text", "") or ""
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    logger.warning(
                        "[LLM] <<< ERROR model=%s attempt=%d/%d elapsed=%.1fs status=%s error=%s",
                        merged.get("model"), attempt + 1, max_retries, elapsed, status_code, str(exc)[:300],
                    )
                    if status_code == 400 and "'temperature' is not supported" in body_text:
                        merged.pop("temperature", None)
                        continue
                    if status_code == 400 and "Stream must be set to true" in body_text:
                        return await self._chat_via_stream(merged)
                    if attempt < max_retries - 1:
                        import random

                        wait = min(2**attempt + random.uniform(0, 1), 30)
                        logger.info("[LLM] Retrying in %.1fs...", wait)
                        await asyncio.sleep(wait)
                        continue
                    raise

    async def _chat_via_stream(self, body: dict[str, Any]) -> str:
        import json

        import httpx

        logger.info("[LLM] >>> STREAM REQUEST model=%s", body.get("model"))
        t0 = time.monotonic()

        headers: dict[str, str] = {}
        api_key = getattr(self._client, "api_key", None) or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request_body = dict(body)
        request_body["stream"] = True
        base_url = str(getattr(self._client, "base_url", "")).rstrip("/")

        content_parts: list[str] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=request_body,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for choice in event.get("choices", []) or []:
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            content_parts.append(text)
        result = "".join(content_parts)
        elapsed = time.monotonic() - t0
        logger.info("[LLM] <<< STREAM RESPONSE model=%s elapsed=%.1fs resp_len=%d", body.get("model"), elapsed, len(result))
        return result
