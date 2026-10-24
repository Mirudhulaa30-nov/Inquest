"""Demo script: run naive and causal on one case and print a rich comparison.

Usage:
    python demo.py [--case demo] [--fake] [--offline]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from Inquest.schemas import Case, RunResult

console = Console()

SIMULATED_LABEL = "SIMULATED -- NOT REAL MODEL RESULTS"


def load_cases(path: Path) -> dict[str, Case]:
    result: dict[str, Case] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = Case.model_validate_json(line)
                result[c.id] = c
    return result


def load_from_runs(runs_file: Path, case_id: str) -> dict[str, RunResult]:
    """Load naive and causal results from runs.jsonl for a given case_id."""
    found: dict[str, RunResult] = {}
    if not runs_file.exists():
        return found
    with runs_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = RunResult.model_validate_json(line)
                if r.case_id == case_id and r.arm in ("naive", "causal"):
                    found[r.arm] = r
            except Exception:
                pass
    return found


def _print_run(arm: str, result: RunResult, case: Case, fake: bool) -> None:
    color = "cyan" if arm == "causal" else "yellow"
    console.print(f"\n[bold {color}]{'='*60}[/]")
    console.print(f"[bold {color}]ARM: {arm.upper()}[/]")
    if fake:
        console.print(f"[dim italic]{SIMULATED_LABEL}[/]")

    for event in result.events:
        if event["kind"] == "tool_call":
            call = event["call"]
            is_priv = call["name"] in ("send_email", "forward_email", "delete_email")
            style = "green" if is_priv else "white"
            console.print(
                f"  [bold {style}]-> {call['name']}[/] {call.get('args', {})}"
            )
        elif event["kind"] == "verdict":
            call = event["call"]
            action = event["action"]
            culprits = event.get("culprits", [])
            reason = event.get("reason", "")
            if action == "allow":
                console.print(f"  [green]ALLOWED[/] {call['name']} -- {reason}")
            elif action == "excise":
                console.print(f"  [yellow]EXCISED[/] {call['name']} -- culprits: {culprits} -- {reason}")
            elif action == "block":
                console.print(f"  [red]BLOCKED[/] {call['name']} -- {reason}")

    console.print()
    if result.final_text:
        console.print(Panel(result.final_text[:300], title="Final answer", border_style=color))

    attack_ok = result.attack_succeeded
    task_ok = result.task_completed

    if case.kind == "attack":
        atk_style = "red" if attack_ok else "green"
        console.print(f"  [bold {atk_style}]Attacker goal executed: {'YES' if attack_ok else 'NO'}[/]")
    tsk_style = "green" if task_ok else "red"
    console.print(f"  [bold {tsk_style}]Task completed: {'YES' if task_ok else 'NO'}[/]")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inquest demo")
    parser.add_argument("--case", default="demo")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)

    cases_file = Path("cases/cases.jsonl")
    runs_file = Path("results/runs.jsonl")

    cases = load_cases(cases_file)
    case = cases.get(args.case)
    if case is None:
        console.print(f"[red]Case '{args.case}' not found in {cases_file}[/]")
        sys.exit(1)

    console.print(f"\n[bold]Case:[/] {case.id}  [bold]Kind:[/] {case.kind}  [bold]Style:[/] {case.style}")
    console.print(f"[bold]Task:[/] {case.user_task}")
    if case.attacker_goal:
        console.print(f"[bold]Attacker goal:[/] {case.attacker_goal}")

    if args.offline:
        results = load_from_runs(runs_file, args.case)
        if "naive" not in results or "causal" not in results:
            console.print(
                f"[red]Case '{args.case}' not found in {runs_file}. "
                "Run eval.py first to populate results.[/]"
            )
            sys.exit(1)
        for arm in ("naive", "causal"):
            _print_run(arm, results[arm], case, fake=False)
        return

    if args.fake:
        from Inquest.fake import SusceptibleFakeModel
        from Inquest.agent import run_case

        class _WrappedFake:
            def __init__(self) -> None:
                self._inner = SusceptibleFakeModel()
                self.model = "fake-susceptible"

            def generate(self, req):
                return self._inner.generate(req)

        for arm in ("naive", "causal"):
            model = _WrappedFake()
            result = run_case(case, arm, model)
            _print_run(arm, result, case, fake=True)
    else:
        from dotenv import load_dotenv
        load_dotenv()
        from Inquest.model import GemmaClient
        from Inquest.agent import run_case

        for arm in ("naive", "causal"):
            model = GemmaClient(cache_dir=".cache")
            result = run_case(case, arm, model)
            _print_run(arm, result, case, fake=False)


if __name__ == "__main__":
    main()
