"""Tests for transcript.py and model.py (no network calls)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from Inquest.schemas import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    QUARANTINE_TEXT,
    REDACTED_TEXT,
    SYSTEM_PROMPT,
)
from Inquest.transcript import Turn, build_request
from Inquest.model import GemmaClient, ModelError


# ---------------------------------------------------------------------------
# build_request tests
# ---------------------------------------------------------------------------


def _make_transcript() -> list[Turn]:
    return [
        Turn(kind="user", text="Read my emails."),
        Turn(kind="call", call=ToolCall(name="list_emails")),
        Turn(
            kind="result",
            call=ToolCall(name="list_emails"),
            result={"emails": [{"id": "e1", "from": "x@corp.example", "subject": "Hi"}]},
        ),
        Turn(
            kind="call",
            call=ToolCall(name="read_email", args={"id": "e1"}),
        ),
        Turn(
            kind="result",
            call=ToolCall(name="read_email", args={"id": "e1"}),
            result={"id": "e1", "from": "x@corp.example", "subject": "Hi", "body": "Hello!"},
            email_id="e1",
        ),
    ]


def test_build_request_no_redaction():
    t = _make_transcript()
    req = build_request("m", t, set(), redact=None)
    assert isinstance(req, ModelRequest)
    # Find the read_email result message
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["body"] == "Hello!"


def test_build_request_redact_all():
    t = _make_transcript()
    req = build_request("m", t, set(), redact="all")
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["body"] == REDACTED_TEXT


def test_build_request_redact_specific_id():
    t = _make_transcript()
    req = build_request("m", t, set(), redact={"e1"})
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["body"] == REDACTED_TEXT


def test_build_request_redact_different_id_no_effect():
    t = _make_transcript()
    req = build_request("m", t, set(), redact={"e99"})
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["body"] == "Hello!"


def test_build_request_quarantine_overrides_redact():
    t = _make_transcript()
    req = build_request("m", t, {"e1"}, redact=None)
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["body"] == QUARANTINE_TEXT


def test_build_request_headers_untouched():
    t = _make_transcript()
    req = build_request("m", t, {"e1"}, redact="all")
    tool_msgs = [m for m in req.messages if m.role == "tool"]
    read_msg = next(m for m in tool_msgs if m.parts[0].name == "read_email")
    assert read_msg.parts[0].response["from"] == "x@corp.example"
    assert read_msg.parts[0].response["subject"] == "Hi"
    assert read_msg.parts[0].response["id"] == "e1"


def test_build_request_does_not_mutate_transcript():
    t = _make_transcript()
    original_body = t[4].result["body"]
    build_request("m", t, {"e1"}, redact="all")
    assert t[4].result["body"] == original_body


def test_build_request_system_prompt():
    t = [Turn(kind="user", text="Hi")]
    req = build_request("m", t, set())
    assert req.system == SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# GemmaClient tests
# ---------------------------------------------------------------------------


def _make_req(salt: int = 0) -> ModelRequest:
    return ModelRequest(
        model="fake-model",
        system="test",
        messages=[],
        temperature=0.0,
        salt=salt,
    )


def test_cache_hit_on_identical_request():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        call_count = 0

        def backend(req: ModelRequest) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            return ModelResponse(text="hi")

        client = GemmaClient(model="fake-model", cache_dir=td, backend=backend)
        req = _make_req()
        r1 = client.generate(req)
        r2 = client.generate(req)
        assert r1.text == r2.text == "hi"
        assert call_count == 1
        assert client.stats.cache_hits == 1
        assert client.stats.api_calls == 1
        client._cache.close()


def test_different_salt_bypasses_cache():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        call_count = 0

        def backend(req: ModelRequest) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            return ModelResponse(text="hi")

        client = GemmaClient(model="fake-model", cache_dir=td, backend=backend)
        client.generate(_make_req(salt=0))
        client.generate(_make_req(salt=1))
        assert call_count == 2
        client._cache.close()


def test_retry_on_transient_failure():
    """Backend fails twice then succeeds; client should retry and return success."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        attempt = 0

        def backend(req: ModelRequest) -> ModelResponse:
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise RuntimeError("transient")
            return ModelResponse(text="ok")

        client = GemmaClient(model="fake-model", cache_dir=td, backend=backend)
        result = client.generate(_make_req())
        assert result.text == "ok"
        assert attempt == 3
        client._cache.close()


def test_raises_model_error_after_exhaustion():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:

        def backend(req: ModelRequest) -> ModelResponse:
            raise RuntimeError("always fails")

        client = GemmaClient(model="fake-model", cache_dir=td, backend=backend)
        with pytest.raises(ModelError):
            client.generate(_make_req())
        client._cache.close()


def test_no_cache_mode():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        call_count = 0

        def backend(req: ModelRequest) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            return ModelResponse(text="no-cache")

        client = GemmaClient(model="fake-model", cache_dir=td, backend=backend, use_cache=False)
        client.generate(_make_req())
        client.generate(_make_req())
        assert call_count == 2
        assert client.stats.cache_hits == 0
