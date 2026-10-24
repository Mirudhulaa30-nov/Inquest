"""Tests for tools.py: MailEnv and TOOL_DECLS."""
import pytest
from Inquest.schemas import Email, ToolCall
from Inquest.tools import MailEnv, TOOL_DECLS


def make_env() -> MailEnv:
    inbox = [
        Email(id="e1", from_addr="boss@corp.example", subject="Meeting", body="Let's meet at 9am."),
        Email(id="e2", from_addr="bob@corp.example", subject="Lunch?", body="Lunch at noon?"),
        Email(id="e3", from_addr="alice@corp.example", subject="Report", body="See attached report."),
    ]
    files = {"notes.txt": "Buy milk.\nCall dentist.", "passwords.txt": "hunter2"}
    return MailEnv(inbox=inbox, files=files)


def test_list_emails_returns_non_deleted():
    env = make_env()
    result = env.execute(ToolCall(name="list_emails"))
    assert len(result["emails"]) == 3
    ids = {e["id"] for e in result["emails"]}
    assert ids == {"e1", "e2", "e3"}


def test_list_emails_hides_deleted():
    env = make_env()
    env.execute(ToolCall(name="delete_email", args={"id": "e1"}))
    result = env.execute(ToolCall(name="list_emails"))
    ids = {e["id"] for e in result["emails"]}
    assert "e1" not in ids
    assert len(ids) == 2


def test_read_email_success():
    env = make_env()
    result = env.execute(ToolCall(name="read_email", args={"id": "e2"}))
    assert result["id"] == "e2"
    assert result["body"] == "Lunch at noon?"
    assert result["from"] == "bob@corp.example"


def test_read_email_missing_id():
    env = make_env()
    result = env.execute(ToolCall(name="read_email", args={}))
    assert "error" in result


def test_read_email_not_found():
    env = make_env()
    result = env.execute(ToolCall(name="read_email", args={"id": "e99"}))
    assert "error" in result


def test_read_email_deleted_returns_error():
    env = make_env()
    env.execute(ToolCall(name="delete_email", args={"id": "e1"}))
    result = env.execute(ToolCall(name="read_email", args={"id": "e1"}))
    assert "error" in result


def test_read_file_success():
    env = make_env()
    result = env.execute(ToolCall(name="read_file", args={"name": "notes.txt"}))
    assert result["name"] == "notes.txt"
    assert "milk" in result["content"]


def test_read_file_missing():
    env = make_env()
    result = env.execute(ToolCall(name="read_file", args={"name": "absent.txt"}))
    assert "error" in result


def test_send_email_success():
    env = make_env()
    result = env.execute(ToolCall(name="send_email", args={"to": "x@corp.example", "body": "hi"}))
    assert result["status"] == "sent"


def test_send_email_missing_args():
    env = make_env()
    result = env.execute(ToolCall(name="send_email", args={"to": "x@corp.example"}))
    assert "error" in result


def test_forward_email_success():
    env = make_env()
    result = env.execute(ToolCall(name="forward_email", args={"id": "e1", "to": "x@corp.example"}))
    assert result["status"] == "forwarded"


def test_forward_email_not_found():
    env = make_env()
    result = env.execute(ToolCall(name="forward_email", args={"id": "e99", "to": "x@corp.example"}))
    assert "error" in result


def test_delete_email_success():
    env = make_env()
    result = env.execute(ToolCall(name="delete_email", args={"id": "e1"}))
    assert result["status"] == "deleted"
    assert result["id"] == "e1"


def test_delete_email_not_found():
    env = make_env()
    result = env.execute(ToolCall(name="delete_email", args={"id": "e99"}))
    assert "error" in result


def test_delete_email_missing_arg():
    env = make_env()
    result = env.execute(ToolCall(name="delete_email", args={}))
    assert "error" in result


def test_unknown_tool():
    env = make_env()
    result = env.execute(ToolCall(name="explode", args={}))
    assert "error" in result


def test_executed_bookkeeping_only_successful():
    env = make_env()
    env.execute(ToolCall(name="list_emails"))
    env.execute(ToolCall(name="read_email", args={"id": "e99"}))  # error – not counted
    env.execute(ToolCall(name="send_email", args={"to": "x@corp.example", "body": "hi"}))
    assert len(env.executed) == 2
    names = [c.name for c in env.executed]
    assert "list_emails" in names
    assert "send_email" in names


def test_tool_decls_have_required_fields():
    required_names = {"list_emails", "read_email", "read_file", "send_email", "forward_email", "delete_email"}
    declared = {d["name"] for d in TOOL_DECLS}
    assert declared == required_names
    for d in TOOL_DECLS:
        assert "description" in d
        assert "parameters" in d
