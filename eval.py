"""Evaluation harness for Inquest.

Usage:
    python eval.py [--fake] [--arms naive strict causal] [--limit N]
                   [--cases cases/cases.jsonl] [--workers 4]
                   [--model MODEL] [--out results] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from Inquest.schemas import Case, RunResult
from Inquest.agent import run_case
from Inquest.scoring import summarize

SIMULATED_LABEL = "SIMULATED -- NOT REAL MODEL RESULTS"
console = Console()


def load_cases(path: Path) -> list[Case]:
    cases = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(Case.model_validate_json(line))
    return cases


def _sample_cases(cases: list[Case], limit: int) -> list[Case]:
    """Round-robin sample across styles to reach *limit* cases."""
    if limit <= 0 or limit >= len(cases):
        return cases
    by_style: dict[str, list[Case]] = {}
    for c in cases:
        by_style.setdefault(c.style, []).append(c)
    styles = sorted(by_style.keys())
    selected: list[Case] = []
    idx = {s: 0 for s in styles}
    while len(selected) < limit:
        added = False
        for s in styles:
            lst = by_style[s]
            i = idx[s]
            if i < len(lst):
                selected.append(lst[i])
                idx[s] += 1
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
    return selected


def _make_model(fake: bool, model_name: str, cache_dir: Path):
    if fake:
        from Inquest.fake import SusceptibleFakeModel

        class _WrappedFake:
            def __init__(self) -> None:
                self._inner = SusceptibleFakeModel()
                self.model = "fake-susceptible"
                self._call_count = 0

            def generate(self, req):
                self._call_count += 1
                return self._inner.generate(req)

        return _WrappedFake()
    else:
        load_dotenv()
        from Inquest.model import GemmaClient
        return GemmaClient(model=model_name, cache_dir=cache_dir)


def _already_done(runs_file: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not runs_file.exists():
        return done
    with runs_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    done.add((d["case_id"], d["arm"]))
                except Exception:
                    pass
    return done


def _make_chart(summary: dict, out_dir: Path, simulated: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    arms = sorted(summary["arms"].keys())
    metrics = ["asr", "benign_completion", "utility_under_attack"]
    labels = ["Attack Success Rate", "Benign Completion", "Utility Under Attack"]
    colors = ["#e74c3c", "#2ecc71", "#3498db"]

    x = np.arange(len(arms))
    width = 0.25

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, (metric, label, color) in enumerate(zip(metrics, labels, colors)):
        vals = []
        for arm in arms:
            v = summary["arms"][arm].get(metric, 0)
            vals.append(0 if (v != v) else v)  # replace nan with 0
        ax.bar(x + i * width, vals, width, label=label, color=color)

    ax.set_xticks(x + width)
    ax.set_xticklabels(arms)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Rate")
    title = "Inquest Results"
    if simulated:
        title += f"\n{SIMULATED_LABEL}"
    ax.set_title(title, fontsize=9)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    out = out_dir / "chart.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)


def _make_summary_md(summary: dict, simulated: bool) -> str:
    lines = []
    if simulated:
        lines.append(f"> {SIMULATED_LABEL}\n")
    lines.append(f"**Model:** {summary['model_name']}  \n")
    lines.append(f"**Total runs:** {summary['total_runs']}  \n\n")

    # Main arm table
    arms = sorted(summary["arms"].keys())
    lines.append("## Arm comparison\n")
    header = "| Arm | ASR | Benign Completion | Utility Under Attack | FIR | Avg Calls |"
    sep = "|-----|-----|-------------------|----------------------|-----|-----------|"
    lines.append(header)
    lines.append(sep)
    for arm in arms:
        a = summary["arms"][arm]
        asr = a.get("asr", float("nan"))
        bc = a.get("benign_completion", float("nan"))
        uua = a.get("utility_under_attack", float("nan"))
        fir = a.get("false_intervention_rate", float("nan"))
        mc = a.get("avg_model_calls", float("nan"))

        def fmt(v):
            return f"{v:.2f}" if v == v else "n/a"

        lines.append(f"| {arm} | {fmt(asr)} | {fmt(bc)} | {fmt(uua)} | {fmt(fir)} | {fmt(mc)} |")

    lines.append("\n## Per-style ASR\n")
    for arm in arms:
        lines.append(f"\n### {arm}\n")
        psa = summary["arms"][arm].get("per_style_asr", {})
        if psa:
            lines.append("| Style | ASR |")
            lines.append("|-------|-----|")
            for style, val in sorted(psa.items()):
                lines.append(f"| {style} | {val:.2f} |")

    lines.append("\n## Limitation styles (non-headline)\n")
    lines.append("| Style | Arm | ASR |")
    lines.append("|-------|-----|-----|")
    for arm in arms:
        lt = summary["arms"][arm].get("limitation_styles", {})
        for style, val in sorted(lt.items()):
            lines.append(f"| {style} | {arm} | {val:.2f} |")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inquest evaluator")
    parser.add_argument("--arms", nargs="+", default=["naive", "strict", "causal"])
    parser.add_argument("--cases", default="cases/cases.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default="results")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_file = out_dir / "runs.jsonl"

    cases = load_cases(Path(args.cases))
    if args.limit > 0:
        cases = _sample_cases(cases, args.limit)

    model_name = args.model or ("fake-susceptible" if args.fake else os.environ.get("GEMMA_MODEL", "gemma-4-26b-a4b-it"))
    done = _already_done(runs_file) if not args.force else set()

    work: list[tuple[Case, str]] = [
        (c, arm)
        for c in cases
        for arm in args.arms
        if (c.id, arm) not in done
    ]

    if not work:
        console.print("[yellow]Nothing to do (all pairs already in runs.jsonl). Use --force to re-run.[/yellow]")
    else:
        console.print(f"Running {len(work)} (case, arm) pairs with {args.workers} workers...")

    results: list[RunResult] = []

    # Load existing results to include in summary
    if runs_file.exists() and not args.force:
        with runs_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(RunResult.model_validate_json(line))
                    except Exception:
                        pass

    def _run_one(pair: tuple[Case, str]) -> RunResult:
        c, arm = pair
        model = _make_model(args.fake, model_name, Path(".cache"))
        return run_case(c, arm, model)

    new_results: list[RunResult] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_one, pair): pair for pair in work}
        for future in as_completed(futures):
            try:
                r = future.result()
                new_results.append(r)
            except Exception as exc:
                pair = futures[future]
                console.print(f"[red]Error on {pair[0].id}/{pair[1]}: {exc}[/red]")

    # Append new results
    if new_results:
        with runs_file.open("a", encoding="utf-8") as f:
            for r in new_results:
                f.write(r.model_dump_json() + "\n")

    results.extend(new_results)

    # Summary
    summary = summarize(results, cases, model_name, simulated=args.fake)

    summary_json = out_dir / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    summary_md_text = _make_summary_md(summary, simulated=args.fake)
    (out_dir / "summary.md").write_text(summary_md_text, encoding="utf-8")

    _make_chart(summary, out_dir, simulated=args.fake)

    # Rich table
    table = Table(title=f"Inquest Results — {SIMULATED_LABEL if args.fake else model_name}")
    table.add_column("Arm")
    table.add_column("ASR")
    table.add_column("Benign Compl.")
    table.add_column("Util Under Attack")
    table.add_column("FIR")
    table.add_column("Avg Calls")

    def fmt(v: float) -> str:
        return f"{v:.2f}" if v == v else "n/a"

    for arm in sorted(summary["arms"].keys()):
        a = summary["arms"][arm]
        table.add_row(
            arm,
            fmt(a.get("asr", float("nan"))),
            fmt(a.get("benign_completion", float("nan"))),
            fmt(a.get("utility_under_attack", float("nan"))),
            fmt(a.get("false_intervention_rate", float("nan"))),
            fmt(a.get("avg_model_calls", float("nan"))),
        )

    console.print(table)

    if args.fake:
        console.print(f"\n[bold yellow]{SIMULATED_LABEL}[/bold yellow]")


if __name__ == "__main__":
    main()
