"""Local HTTP and SSE server for the Inquest web interface."""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from Inquest.schemas import Case, RunResult


ROOT = Path(__file__).resolve().parent
CASES_FILE = ROOT / "cases" / "cases.jsonl"
FRONTEND_DIST = ROOT / "frontend" / "dist"
_RESULTS_LOCK = threading.Lock()


def load_cases() -> dict[str, Case]:
    """Load cases from the project's JSONL dataset."""
    cases: dict[str, Case] = {}
    with CASES_FILE.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                case = Case.model_validate_json(line)
                cases[case.id] = case
    return cases


def _json_safe(value: Any) -> Any:
    """Convert nested values to strict JSON-compatible data."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class InquestHandler(SimpleHTTPRequestHandler):
    """Serve the built frontend and a small local JSON/SSE API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FRONTEND_DIST), **kwargs)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, data: Any, status: int = 200) -> None:
        raw = json.dumps(_json_safe(data), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/cases":
            cases = load_cases()
            self._send_json([
                {
                    "id": case.id,
                    "kind": case.kind,
                    "style": case.style,
                    "task": case.user_task,
                    "headline": case.headline,
                    "required_calls": [call.model_dump() for call in case.required_calls],
                    "attacker_goal": case.attacker_goal.model_dump() if case.attacker_goal else None,
                }
                for case in cases.values()
            ])
            return
        if route == "/api/results":
            self._send_json(self._read_results())
            return
        if not FRONTEND_DIST.exists():
            message = (
                "Inquest UI is not built yet. Start the development server with "
                "`cd frontend && npm run dev`, or run `npm run build` first."
            )
            self.send_error(503, message)
            return
        if route not in ("/",) and not (FRONTEND_DIST / route.lstrip("/")).exists():
            self.path = "/"
        super().do_GET()

    def _read_results(self) -> dict[str, Any]:
        runs_file = ROOT / "results" / "runs.jsonl"
        if not runs_file.exists():
            return {"available": False, "summary": None, "recent_runs": []}
        runs: list[RunResult] = []
        with runs_file.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    try:
                        runs.append(RunResult.model_validate_json(line))
                    except ValueError:
                        continue
        from Inquest.scoring import summarize

        cases = list(load_cases().values())
        model_name = runs[-1].model_name if runs else ""
        modes = {run.model_name.startswith("fake") for run in runs}
        summary = summarize(runs, cases, model_name, simulated=modes == {True})
        summary["mixed_modes"] = len(modes) > 1
        return {
            "available": bool(runs),
            "summary": summary,
            "recent_runs": [run.model_dump(mode="json") for run in runs[-20:][::-1]],
        }

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self._send_json({"error": "Not found"}, 404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 16_384:
                raise ValueError("Request is too large")
            request = json.loads(self.rfile.read(size))
            case_id = str(request.get("case_id", ""))
            arm = str(request.get("arm", "causal"))
            simulated = bool(request.get("fake", True))
            case = load_cases().get(case_id)
            if case is None:
                self._send_json({"error": "Unknown case"}, 404)
                return
            if arm not in {"naive", "strict", "causal"}:
                self._send_json({"error": "Unknown defense arm"}, 400)
                return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        events: queue.Queue[dict[str, Any]] = queue.Queue()

        def run() -> None:
            try:
                from Inquest.agent import run_case

                if simulated:
                    from Inquest.fake import SusceptibleFakeModel

                    class FakeAdapter:
                        model = "fake-susceptible"

                        def __init__(self) -> None:
                            self.inner = SusceptibleFakeModel()

                        def generate(self, req: Any) -> Any:
                            return self.inner.generate(req)

                    model = FakeAdapter()
                else:
                    from dotenv import load_dotenv
                    from Inquest.model import GemmaClient

                    load_dotenv(ROOT / ".env")
                    if not os.environ.get("GEMINI_API_KEY"):
                        events.put({
                            "kind": "error",
                            "message": "GEMINI_API_KEY is missing. Add it to the repository-root .env file, then restart gui_server.py.",
                        })
                        return
                    model = GemmaClient(cache_dir=ROOT / ".cache")

                result = run_case(case, arm, model, on_event=events.put)
                results_path = ROOT / "results" / "runs.jsonl"
                results_path.parent.mkdir(parents=True, exist_ok=True)
                with _RESULTS_LOCK, results_path.open("a", encoding="utf-8") as output:
                    output.write(result.model_dump_json() + "\n")
                events.put({"kind": "done", "result": result.model_dump(mode="json"), "fake": simulated})
            except Exception as exc:
                events.put({"kind": "error", "message": str(exc)})

        threading.Thread(target=run, daemon=True).start()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                event = events.get()
                chunk = f"data: {json.dumps(_json_safe(event), ensure_ascii=False)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
                if event.get("kind") in {"done", "error"}:
                    break
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Inquest web GUI server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), InquestHandler)
    print(f"Inquest API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
