"""Main agent loop: run_case and decide dispatcher."""
from __future__ import annotations

from typing import Any

from Inquest.schemas import (
    PRIVILEGED,
    Case,
    RunResult,
    ToolCall,
    Verdict,
)
from Inquest.tools import MailEnv
from Inquest.transcript import Turn, build_request
from Inquest.model import ModelError
import Inquest.strict as strict_mod
import Inquest.attribution as attribution_mod
import Inquest.scoring as scoring_mod


def decide(
    arm: str,
    call: ToolCall,
    transcript: list[Turn],
    quarantined: set[str],
    model: Any,
) -> Verdict:
    """Route to the appropriate defense arm."""
    if arm == "naive":
        return Verdict(action="allow", reason="naive: no defense")
    if arm == "strict":
        return strict_mod.decide(call, transcript, quarantined, model)
    if arm == "causal":
        return attribution_mod.decide(call, transcript, quarantined, model)
    raise ValueError(f"Unknown arm: {arm!r}")


def run_case(
    case: Case,
    arm: str,
    model: Any,
    max_steps: int = 8,
    max_excisions: int = 3,
) -> RunResult:
    """Run *case* under defense *arm* and return a RunResult."""
    env = MailEnv(case.inbox, case.files)
    transcript: list[Turn] = [Turn(kind="user", text=case.user_task)]
    quarantined: set[str] = set()

    step = 0
    excisions = 0
    model_calls = 0
    events: list[dict[str, Any]] = []
    executed: list[ToolCall] = []
    blocked: list[ToolCall] = []
    excised_ids: list[str] = []
    final_text = ""
    error: str | None = None

    try:
        while step < max_steps:
            req = build_request(model.model if hasattr(model, "model") else "fake", transcript, quarantined, redact=None)
            resp = model.generate(req)
            model_calls += 1

            if not resp.calls:
                final_text = resp.text
                break

            restart = False
            for call in resp.calls:
                if call.name in PRIVILEGED:
                    v = decide(arm, call, transcript, quarantined, model)
                    model_calls += v.model_calls
                    events.append(
                        {
                            "kind": "verdict",
                            "call": call.model_dump(),
                            "action": v.action,
                            "culprits": v.culprits,
                            "reason": v.reason,
                        }
                    )

                    if v.action == "excise" and excisions < max_excisions:
                        for cid in v.culprits:
                            if cid not in quarantined:
                                quarantined.add(cid)
                                excised_ids.append(cid)
                        excisions += 1
                        restart = True
                        break

                    if v.action in ("block", "excise"):
                        # excise limit reached → treat as block
                        transcript.append(Turn(kind="call", call=call))
                        transcript.append(
                            Turn(
                                kind="result",
                                call=call,
                                result={"error": "blocked by policy"},
                            )
                        )
                        blocked.append(call)
                        continue

                    # action == "allow": fall through to execute

                result = env.execute(call)
                email_id = None
                if call.name == "read_email" and "error" not in result:
                    email_id = result.get("id")

                transcript.append(Turn(kind="call", call=call))
                transcript.append(
                    Turn(
                        kind="result",
                        call=call,
                        result=result,
                        email_id=email_id,
                    )
                )
                if "error" not in result:
                    executed.append(call)
                events.append({"kind": "tool_call", "call": call.model_dump(), "result": result})

            if restart:
                continue

            step += 1

    except ModelError as exc:
        error = str(exc)

    result_obj = RunResult(
        case_id=case.id,
        arm=arm,
        model_name=model.model if hasattr(model, "model") else "fake",
        executed=executed,
        blocked=blocked,
        excised_ids=excised_ids,
        events=events,
        final_text=final_text,
        steps=step,
        model_calls=model_calls,
        error=error,
    )

    # Score
    result_obj = scoring_mod.score_run(result_obj, case, executed, final_text, blocked, excised_ids)
    return result_obj
