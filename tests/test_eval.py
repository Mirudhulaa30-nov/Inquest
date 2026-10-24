"""Tests for eval.py: fake mode, output files, SIMULATED label."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest


def test_eval_fake_limit_produces_outputs():
    """Run eval.py --fake --limit 12 and verify all output files exist."""
    import subprocess, sys

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        result = subprocess.run(
            [
                sys.executable,
                "eval.py",
                "--fake",
                "--limit", "12",
                "--out", td,
                "--force",
                "--workers", "2",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"eval.py failed:\n{result.stdout}\n{result.stderr}"

        out = Path(td)
        assert (out / "runs.jsonl").exists()
        assert (out / "summary.json").exists()
        assert (out / "summary.md").exists()
        assert (out / "chart.png").exists()


def test_eval_simulated_label_in_outputs():
    import subprocess, sys
    from eval import SIMULATED_LABEL

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        subprocess.run(
            [sys.executable, "eval.py", "--fake", "--limit", "6", "--out", td, "--force"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        summary_md = (Path(td) / "summary.md").read_text(encoding="utf-8")
        assert SIMULATED_LABEL in summary_md

        summary_json = json.loads((Path(td) / "summary.json").read_text(encoding="utf-8"))
        assert summary_json["simulated"] is True


def test_eval_runs_jsonl_format():
    import subprocess, sys

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        subprocess.run(
            [sys.executable, "eval.py", "--fake", "--limit", "6", "--out", td, "--force"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        runs_file = Path(td) / "runs.jsonl"
        from Inquest.schemas import RunResult
        with runs_file.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    r = RunResult.model_validate_json(line)
                    assert r.case_id
                    assert r.arm in ("naive", "strict", "causal")
