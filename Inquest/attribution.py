"""Causal excision defense: attribute privileged calls to individual emails."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from Inquest.schemas import ToolCall, Verdict, same_call
from Inquest.transcript import Turn, build_request


def decide(
    call: ToolCall,
    transcript: list[Turn],
    quarantined: set[str],
    model: Any,
    workers: int = 4,
) -> Verdict:
    """Causal attribution decision for a privileged *call*.

    Returns a Verdict with action "allow", "excise", or "block".
    """
    # Collect ids of read_email results not already quarantined
    read_ids: list[str] = [
        t.email_id
        for t in transcript
        if t.kind == "result"
        and t.call is not None
        and t.call.name == "read_email"
        and t.email_id is not None
        and t.email_id not in quarantined
    ]

    if not read_ids:
        return Verdict(
            action="allow",
            reason="no untrusted content",
            model_calls=0,
        )

    model_name = model.model if hasattr(model, "model") else "fake"
    extra_calls = 0

    def _propose(redact: Any) -> list[ToolCall]:
        req = build_request(model_name, transcript, quarantined, redact=redact, salt=extra_calls)
        resp = model.generate(req)
        return resp.calls

    # Step 1: re-run with all bodies redacted
    req_all = build_request(model_name, transcript, quarantined, redact="all", salt=1)
    resp_all = model.generate(req_all)
    extra_calls += 1

    persists = any(same_call(c, call) for c in resp_all.calls)
    if persists:
        return Verdict(
            action="allow",
            reason="persists without email bodies: user-driven",
            model_calls=extra_calls,
        )

    # Step 2: per-email ablation (parallel)
    culprits: list[str] = []

    def _check_id(eid: str) -> tuple[str, bool]:
        req = build_request(model_name, transcript, quarantined, redact={eid}, salt=2)
        resp = model.generate(req)
        # culprit if the call disappears when this email is removed
        still_present = any(same_call(c, call) for c in resp.calls)
        return (eid, not still_present)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check_id, eid): eid for eid in read_ids}
        for future in as_completed(futures):
            eid, is_culprit = future.result()
            extra_calls += 1
            if is_culprit:
                culprits.append(eid)

    if culprits:
        return Verdict(
            action="excise",
            culprits=culprits,
            reason=f"email(s) {culprits} caused the privileged call",
            model_calls=extra_calls,
        )

    return Verdict(
        action="block",
        reason="depends on untrusted content; no single email explains it",
        model_calls=extra_calls,
    )
