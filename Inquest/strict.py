"""Strict baseline defense: block any privileged call if any email has been read."""
from __future__ import annotations

from Inquest.schemas import ToolCall, Verdict
from Inquest.transcript import Turn


def decide(
    call: ToolCall,
    transcript: list[Turn],
    quarantined: set[str],
    model: object,
) -> Verdict:
    """Block *call* if any read_email result exists in *transcript*; else allow."""
    for turn in transcript:
        if (
            turn.kind == "result"
            and turn.call is not None
            and turn.call.name == "read_email"
        ):
            return Verdict(
                action="block",
                reason="strict: privileged call after reading email bodies",
            )
    return Verdict(action="allow", reason="strict: no email bodies read yet")
