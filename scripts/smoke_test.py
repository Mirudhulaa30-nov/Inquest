"""Smoke test: verify the real Gemma model is reachable and behaves as expected.

Run with a real API key: python scripts/smoke_test.py

Exits with code 0 and prints SMOKE TEST OK on success.
Exits with code 1 and prints failure details otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from Inquest.model import GemmaClient
from Inquest.schemas import Message, ModelRequest, Part, ToolCall
from Inquest.transcript import Turn, build_request


def main() -> int:
    client = GemmaClient(use_cache=False)

    # ----------------------------------------------------------------
    # Test 1: ask for an email to bob@example.com
    # ----------------------------------------------------------------
    transcript: list[Turn] = [
        Turn(kind="user", text="Please send an email to bob@example.com saying hello.")
    ]
    req = build_request(client.model, transcript, set(), redact=None)

    try:
        resp = client.generate(req)
    except Exception as exc:
        print(f"SMOKE TEST FAILED (test 1 — model call): {exc}")
        return 1

    send_calls = [c for c in resp.calls if c.name == "send_email"]
    if not send_calls:
        print(f"SMOKE TEST FAILED (test 1 — expected send_email call, got): {resp.calls}")
        return 1

    to_val = send_calls[0].args.get("to", "")
    if "bob@example.com" not in str(to_val):
        print(f"SMOKE TEST FAILED (test 1 — expected to=bob@example.com, got): {to_val!r}")
        return 1

    # ----------------------------------------------------------------
    # Test 2: send back a tool result and expect non-empty text
    # ----------------------------------------------------------------
    call = send_calls[0]
    transcript.append(Turn(kind="call", call=call))
    transcript.append(
        Turn(
            kind="result",
            call=call,
            result={"status": "sent", "to": to_val},
        )
    )
    req2 = build_request(client.model, transcript, set(), redact=None)

    try:
        resp2 = client.generate(req2)
    except Exception as exc:
        print(f"SMOKE TEST FAILED (test 2 — model call): {exc}")
        return 1

    if not resp2.text.strip():
        print(f"SMOKE TEST FAILED (test 2 — expected non-empty text, got empty)")
        return 1

    print("SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
