"""Turn representation and request builder with redaction/quarantine."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from Inquest.schemas import (
    Message,
    ModelRequest,
    Part,
    ToolCall,
    QUARANTINE_TEXT,
    REDACTED_TEXT,
    SYSTEM_PROMPT,
)


class Turn(BaseModel):
    """A single entry in the conversation transcript."""

    kind: str  # "user" | "call" | "result"
    text: str | None = None
    call: ToolCall | None = None
    result: dict[str, Any] | None = None
    email_id: str | None = None


def build_request(
    model: str,
    transcript: list[Turn],
    quarantined: set[str],
    redact: None | str | set[str] = None,
    salt: int = 0,
) -> ModelRequest:
    """Convert *transcript* into a ModelRequest.

    Parameters
    ----------
    model:
        Model identifier string.
    transcript:
        Ordered list of turns.
    quarantined:
        Set of email ids whose bodies should be replaced with QUARANTINE_TEXT.
    redact:
        None → no redaction; ``"all"`` → redact all email bodies not quarantined;
        set[str] → redact only the listed ids (that are not quarantined).
    salt:
        Tiebreaker so two otherwise-identical requests hash differently.
    """
    messages: list[Message] = []

    for turn in transcript:
        if turn.kind == "user":
            messages.append(
                Message(role="user", parts=[Part(kind="text", text=turn.text)])
            )
        elif turn.kind == "call":
            assert turn.call is not None
            messages.append(
                Message(
                    role="model",
                    parts=[Part(kind="call", name=turn.call.name, args=turn.call.args)],
                )
            )
        elif turn.kind == "result":
            assert turn.result is not None and turn.call is not None
            result = _apply_redaction(turn, quarantined, redact)
            messages.append(
                Message(
                    role="tool",
                    parts=[
                        Part(
                            kind="result",
                            name=turn.call.name,
                            response=result,
                        )
                    ],
                )
            )

    return ModelRequest(
        model=model,
        system=SYSTEM_PROMPT,
        messages=messages,
        temperature=0.0,
        salt=salt,
    )


def _apply_redaction(
    turn: Turn,
    quarantined: set[str],
    redact: None | str | set[str],
) -> dict[str, Any]:
    """Return (possibly modified) result dict; never mutates the original."""
    result = turn.result
    assert result is not None

    if turn.call is None or turn.call.name != "read_email":
        return result

    eid = turn.email_id
    if eid is None:
        return result

    if eid in quarantined:
        return {**result, "body": QUARANTINE_TEXT}

    if redact == "all":
        return {**result, "body": REDACTED_TEXT}

    if isinstance(redact, set) and eid in redact:
        return {**result, "body": REDACTED_TEXT}

    return result
