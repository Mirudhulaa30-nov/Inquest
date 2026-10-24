"""Tests for cases/cases.jsonl."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from Inquest.schemas import Case

CASES_FILE = Path(__file__).parent.parent / "cases" / "cases.jsonl"


def load_cases() -> list[Case]:
    cases = []
    with CASES_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(Case.model_validate_json(line))
    return cases


# We also need to load the raw dicts to check domains
def load_raw() -> list[dict]:
    raw = []
    with CASES_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw.append(json.loads(line))
    return raw


def _all_text(raw: dict) -> str:
    """Recursively extract all string values from a dict."""
    parts = []
    if isinstance(raw, dict):
        for v in raw.values():
            parts.append(_all_text(v))
    elif isinstance(raw, list):
        for item in raw:
            parts.append(_all_text(item))
    elif isinstance(raw, str):
        parts.append(raw)
    return " ".join(parts)


_REAL_DOMAIN_RE = re.compile(
    r"@(?!.*\.example\b)[\w.-]+\.(com|org|net|io|co|gov|edu)\b",
    re.IGNORECASE,
)


def test_file_exists():
    assert CASES_FILE.exists(), "cases.jsonl not found"


def test_total_count():
    cases = load_cases()
    assert len(cases) == 59, f"Expected 59 cases, got {len(cases)}"


def test_unique_ids():
    cases = load_cases()
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "Duplicate case ids found"


def test_headline_attack_count():
    cases = load_cases()
    hl = [c for c in cases if c.kind == "attack" and c.headline]
    assert len(hl) >= 35, f"Expected ≥35 headline attack cases, got {len(hl)}"


def test_benign_count():
    cases = load_cases()
    benign = [c for c in cases if c.kind == "benign"]
    assert len(benign) >= 15, f"Expected ≥15 benign cases, got {len(benign)}"


def test_demo_exists():
    cases = load_cases()
    ids = {c.id for c in cases}
    assert "demo" in ids, "No case with id 'demo'"


def test_demo_is_attack():
    cases = load_cases()
    demo = next(c for c in cases if c.id == "demo")
    assert demo.kind == "attack"
    assert demo.style == "direct_command"


def test_only_example_domains():
    raws = load_raw()
    for raw in raws:
        text = _all_text(raw)
        matches = _REAL_DOMAIN_RE.findall(text)
        assert not matches, f"Real domain found in case {raw.get('id')}: {matches}"


def test_all_cases_validate():
    """All lines must parse as valid Case objects."""
    cases = load_cases()
    for c in cases:
        assert isinstance(c, Case)


def test_attack_cases_have_attacker_goal():
    cases = load_cases()
    for c in cases:
        if c.kind == "attack":
            assert c.attacker_goal is not None, f"Attack case {c.id} has no attacker_goal"


def test_attack_attacker_goal_uses_example_domain():
    cases = load_cases()
    for c in cases:
        if c.kind == "attack" and c.attacker_goal:
            addr = c.attacker_goal.args.get("to", "")
            if addr and addr != "*":
                assert addr.endswith(".example"), f"Non .example attacker addr in case {c.id}: {addr}"


def test_redundant_payload_cases_exist():
    cases = load_cases()
    rp = [c for c in cases if c.style == "redundant_payload"]
    assert len(rp) >= 3


def test_subject_injection_cases_exist():
    cases = load_cases()
    si = [c for c in cases if c.style == "subject_injection"]
    assert len(si) >= 3
