"""Tests for schemas.py: call_matches, same_call, norm."""
import pytest
from Inquest.schemas import (
    ToolCall,
    ExpectedCall,
    call_matches,
    same_call,
    norm,
    PRIVILEGED,
    READ_TOOLS,
    KEY_ARGS,
)


def test_norm_strips_and_lowercases():
    assert norm("  Alice@CORP.EXAMPLE  ") == "alice@corp.example"
    assert norm("Hello") == "hello"


def test_call_matches_exact():
    call = ToolCall(name="send_email", args={"to": "bob@corp.example", "body": "hi"})
    exp = ExpectedCall(tool="send_email", args={"to": "bob@corp.example"})
    assert call_matches(call, exp)


def test_call_matches_wildcard():
    call = ToolCall(name="forward_email", args={"to": "x@evil.example", "id": "e3"})
    exp = ExpectedCall(tool="forward_email", args={"to": "x@evil.example", "id": "*"})
    assert call_matches(call, exp)


def test_call_matches_wrong_tool():
    call = ToolCall(name="delete_email", args={"id": "e1"})
    exp = ExpectedCall(tool="send_email", args={"to": "boss@corp.example"})
    assert not call_matches(call, exp)


def test_call_matches_wrong_value():
    call = ToolCall(name="send_email", args={"to": "alice@corp.example"})
    exp = ExpectedCall(tool="send_email", args={"to": "boss@corp.example"})
    assert not call_matches(call, exp)


def test_call_matches_missing_arg():
    call = ToolCall(name="send_email", args={"body": "hi"})
    exp = ExpectedCall(tool="send_email", args={"to": "boss@corp.example"})
    assert not call_matches(call, exp)


def test_call_matches_norm_case_insensitive():
    call = ToolCall(name="send_email", args={"to": "  BOSS@CORP.EXAMPLE  "})
    exp = ExpectedCall(tool="send_email", args={"to": "boss@corp.example"})
    assert call_matches(call, exp)


def test_same_call_matching():
    a = ToolCall(name="send_email", args={"to": "x@evil.example", "body": "pwned"})
    b = ToolCall(name="send_email", args={"to": "x@evil.example", "subject": "other"})
    assert same_call(a, b)


def test_same_call_different_to():
    a = ToolCall(name="send_email", args={"to": "a@evil.example"})
    b = ToolCall(name="send_email", args={"to": "b@evil.example"})
    assert not same_call(a, b)


def test_same_call_different_tool():
    a = ToolCall(name="send_email", args={"to": "x@evil.example"})
    b = ToolCall(name="forward_email", args={"to": "x@evil.example", "id": "e1"})
    assert not same_call(a, b)


def test_same_call_delete_email():
    a = ToolCall(name="delete_email", args={"id": "e4"})
    b = ToolCall(name="delete_email", args={"id": "e4"})
    assert same_call(a, b)


def test_same_call_delete_different_id():
    a = ToolCall(name="delete_email", args={"id": "e4"})
    b = ToolCall(name="delete_email", args={"id": "e5"})
    assert not same_call(a, b)


def test_same_call_no_key_args_tool():
    """Tools not in KEY_ARGS compare as equal if same name (no keys to check)."""
    a = ToolCall(name="list_emails", args={})
    b = ToolCall(name="list_emails", args={})
    assert same_call(a, b)


def test_constants_disjoint():
    assert PRIVILEGED.isdisjoint(READ_TOOLS)


def test_key_args_subset_of_privileged():
    assert set(KEY_ARGS.keys()).issubset(PRIVILEGED)
