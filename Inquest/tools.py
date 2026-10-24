"""Tool declarations and MailEnv runtime for Inquest."""
from __future__ import annotations

from typing import Any

from Inquest.schemas import Email, ToolCall

# ---------------------------------------------------------------------------
# Tool declarations (plain dicts as required by the SDK constraint)
# ---------------------------------------------------------------------------

TOOL_DECLS: list[dict[str, Any]] = [
    {
        "name": "list_emails",
        "description": "List all non-deleted emails in the inbox (id, from, subject only).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_email",
        "description": "Read the full content of an email by id.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Email id to read."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the inbox attachment store by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name to read."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "send_email",
        "description": "Send a new email. PRIVILEGED.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient address."},
                "body": {"type": "string", "description": "Email body text."},
                "subject": {"type": "string", "description": "Email subject (optional)."},
            },
            "required": ["to", "body"],
        },
    },
    {
        "name": "forward_email",
        "description": "Forward an existing email to a new recipient. PRIVILEGED.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Id of the email to forward."},
                "to": {"type": "string", "description": "Recipient address."},
            },
            "required": ["id", "to"],
        },
    },
    {
        "name": "delete_email",
        "description": "Permanently delete an email by id. PRIVILEGED.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Id of the email to delete."},
            },
            "required": ["id"],
        },
    },
]


# ---------------------------------------------------------------------------
# MailEnv: runtime execution environment
# ---------------------------------------------------------------------------


class MailEnv:
    """Stateful inbox environment that executes tool calls."""

    def __init__(self, inbox: list[Email], files: dict[str, str] | None = None) -> None:
        self._emails: dict[str, Email] = {e.id: e for e in inbox}
        self._deleted: set[str] = set()
        self._files: dict[str, str] = files or {}
        self.executed: list[ToolCall] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _email_visible(self, eid: str) -> bool:
        return eid in self._emails and eid not in self._deleted

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    def _list_emails(self, _args: dict[str, Any]) -> dict[str, Any]:
        emails = [
            {"id": e.id, "from": e.from_addr, "subject": e.subject}
            for eid, e in self._emails.items()
            if eid not in self._deleted
        ]
        return {"emails": emails}

    def _read_email(self, args: dict[str, Any]) -> dict[str, Any]:
        eid = args.get("id")
        if not eid:
            return {"error": "missing required argument: id"}
        if not self._email_visible(str(eid)):
            return {"error": f"email not found: {eid}"}
        e = self._emails[str(eid)]
        return {"id": e.id, "from": e.from_addr, "subject": e.subject, "body": e.body}

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not name:
            return {"error": "missing required argument: name"}
        name = str(name)
        if name not in self._files:
            return {"error": f"file not found: {name}"}
        return {"name": name, "content": self._files[name]}

    def _send_email(self, args: dict[str, Any]) -> dict[str, Any]:
        if "to" not in args or "body" not in args:
            return {"error": "missing required arguments: to, body"}
        return {"status": "sent", "to": args["to"]}

    def _forward_email(self, args: dict[str, Any]) -> dict[str, Any]:
        eid = args.get("id")
        to = args.get("to")
        if not eid or not to:
            return {"error": "missing required arguments: id, to"}
        if not self._email_visible(str(eid)):
            return {"error": f"email not found: {eid}"}
        return {"status": "forwarded", "id": eid, "to": to}

    def _delete_email(self, args: dict[str, Any]) -> dict[str, Any]:
        eid = args.get("id")
        if not eid:
            return {"error": "missing required argument: id"}
        eid = str(eid)
        if not self._email_visible(eid):
            return {"error": f"email not found: {eid}"}
        self._deleted.add(eid)
        return {"status": "deleted", "id": eid}

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    _HANDLERS = {
        "list_emails": _list_emails,
        "read_email": _read_email,
        "read_file": _read_file,
        "send_email": _send_email,
        "forward_email": _forward_email,
        "delete_email": _delete_email,
    }

    def execute(self, call: ToolCall) -> dict[str, Any]:
        """Execute *call* and return the result dict (never raises)."""
        handler = self._HANDLERS.get(call.name)
        if handler is None:
            return {"error": f"unknown tool: {call.name}"}
        result = handler(self, call.args)
        if "error" not in result:
            self.executed.append(call)
        return result
