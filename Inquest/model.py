"""GemmaClient with disk cache and retry, plus SDK translation helpers."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable

import diskcache
import tenacity

from Inquest.schemas import (
    Message,
    ModelRequest,
    ModelResponse,
    Part,
    ToolCall,
    SYSTEM_PROMPT,
)
from Inquest.tools import TOOL_DECLS


class ModelError(RuntimeError):
    """Raised when all retry attempts are exhausted."""


# ---------------------------------------------------------------------------
# SDK translation  (UNVERIFIED — isolates all google-genai SDK specifics)
# ---------------------------------------------------------------------------


def _to_sdk(req: ModelRequest) -> dict[str, Any]:
    """Convert our ModelRequest to keyword args for the SDK generate call.

    Returns a dict with keys: ``model``, ``contents``, ``config``.
    UNVERIFIED: exact SDK surface may differ from actual google-genai release.
    """
    from google.genai import types  # type: ignore[import]

    contents: list[Any] = []
    for msg in req.messages:
        parts_sdk: list[Any] = []
        for p in msg.parts:
            if p.kind == "text":
                parts_sdk.append(types.Part.from_text(text=p.text or ""))
            elif p.kind == "call":
                parts_sdk.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            name=p.name,
                            args=p.args or {},
                        )
                    )
                )
            elif p.kind == "result":
                parts_sdk.append(
                    types.Part.from_function_response(
                        name=p.name,
                        response=p.response or {},
                    )
                )
        role = "model" if msg.role == "model" else "user"
        contents.append(types.Content(role=role, parts=parts_sdk))

    tool_obj = types.Tool(function_declarations=TOOL_DECLS)
    config = types.GenerateContentConfig(
        tools=[tool_obj],
        temperature=req.temperature,
        system_instruction=req.system,
    )
    return {"model": req.model, "contents": contents, "config": config}


def _from_sdk(resp: Any) -> ModelResponse:
    """Convert an SDK response to our ModelResponse.

    UNVERIFIED: exact attribute paths may differ from actual google-genai release.
    """
    calls: list[ToolCall] = []
    text_parts: list[str] = []

    candidate = resp.candidates[0]
    for part in candidate.content.parts:
        fc = getattr(part, "function_call", None)
        if fc is not None and fc.name:
            calls.append(ToolCall(name=fc.name, args=dict(fc.args or {})))
        else:
            t = getattr(part, "text", None)
            if t:
                text_parts.append(t)

    return ModelResponse(calls=calls, text=" ".join(text_parts))


# ---------------------------------------------------------------------------
# GemmaClient
# ---------------------------------------------------------------------------


class _Stats:
    def __init__(self) -> None:
        self.api_calls: int = 0
        self.cache_hits: int = 0


class GemmaClient:
    """Caching, retrying wrapper around the Gemma model backend."""

    DEFAULT_MODEL = "gemma-4-26b-a4b-it"

    def __init__(
        self,
        model: str | None = None,
        cache_dir: str | Path = ".cache",
        backend: Callable[[ModelRequest], ModelResponse] | None = None,
        use_cache: bool = True,
    ) -> None:
        self.model = model or os.environ.get("GEMMA_MODEL", self.DEFAULT_MODEL)
        self._cache_dir = Path(cache_dir)
        self._use_cache = use_cache
        self._backend = backend or self._live_backend
        self._cache: diskcache.Cache | None = None
        if use_cache:
            self._cache = diskcache.Cache(str(self._cache_dir))
        self.stats = _Stats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, req: ModelRequest) -> ModelResponse:
        """Generate a response, using the disk cache when available."""
        key = hashlib.sha256(req.model_dump_json().encode()).hexdigest()

        if self._use_cache and self._cache is not None:
            if key in self._cache:
                self.stats.cache_hits += 1
                return ModelResponse.model_validate(self._cache[key])

        result = self._call_with_retry(req)
        self.stats.api_calls += 1

        if self._use_cache and self._cache is not None:
            self._cache[key] = result.model_dump()

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_with_retry(self, req: ModelRequest) -> ModelResponse:
        @tenacity.retry(
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_exponential(multiplier=1, max=30),
            reraise=True,
        )
        def _attempt() -> ModelResponse:
            return self._backend(req)

        try:
            return _attempt()
        except Exception as exc:
            raise ModelError(f"Model call failed after retries: {exc}") from exc

    def _live_backend(self, req: ModelRequest) -> ModelResponse:
        """Call the real Gemma model via the google-genai SDK."""
        from google import genai  # type: ignore[import]

        client = genai.Client()
        sdk_kwargs = _to_sdk(req)
        resp = client.models.generate_content(**sdk_kwargs)
        return _from_sdk(resp)
