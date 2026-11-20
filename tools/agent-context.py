#!/usr/bin/env python3
"""Answer an ACP worker's policy decisions and save points beside it in its sandbox.
It runs no file or terminal callbacks: the agent runs its own tools there."""
from __future__ import annotations

import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

LIMIT = 1024 * 1024


class Context:
    def __init__(self, run_id: str, runtime_root: str) -> None:
        self.run_id = run_id
        self.runtime_root = runtime_root

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if params.pop("runId", None) != self.run_id:
            raise ValueError("context run does not match")
        if method == "policy":
            if not self.runtime_root:
                raise ValueError("policy runtime is not configured")
            sys.path.insert(0, self.runtime_root)
            evaluate_tool = importlib.import_module("arivu.policy").evaluate_tool
            captured: list[str] = []
            def consent(reason: str, *_args: Any, **_kwargs: Any) -> bool:
                captured.append(reason)
                return False
            decision = evaluate_tool(params["tool"], params["input"], params.get("session_id", self.run_id),
                                     consent_prompter=consent, cwd=params.get("cwd") or os.getcwd())
            return {"allowed": None if captured else decision[0],
                    "reason": captured[0] if captured else decision[1]}
        if method == "save":
            if not self.runtime_root:
                raise ValueError("save runtime is not configured")
            sys.path.insert(0, self.runtime_root)
            save_before = importlib.import_module("arivu.save_point").save_before
            result = save_before(params["command"], params.get("cwd") or os.getcwd())
            return {"saved": result}
        raise ValueError("unknown context method")


def main() -> int:
    directory, run_id, runtime_root, *command = sys.argv[1:]
    endpoint = Path(directory) / "context.sock"
    context = Context(run_id, runtime_root)
    server = socket.socket(socket.AF_UNIX)
    # Never unlink somebody else's endpoint. Each invocation needs a fresh dir.
    server.bind(str(endpoint))
    endpoint.chmod(0o600)
    server.listen(8)
    stopping = threading.Event()
    slots = threading.BoundedSemaphore(8)

    def handle(connection: socket.socket) -> None:
        request_id = None
        try:
            connection.settimeout(30)
            with connection.makefile("rb") as reader:
                line = reader.readline(LIMIT + 1)
                if len(line) > LIMIT or not line.endswith(b"\n"):
                    raise ValueError("context request exceeds limit or is incomplete")
                request = json.loads(line)
                request_id = request["id"]
                result = context.call(request["method"], request["params"])
                response = {"id": request_id, "result": result}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, ArithmeticError, subprocess.SubprocessError) as error:
            response = {"id": request_id, "error": {"message": str(error)}}
        try:
            payload = (json.dumps(response, ensure_ascii=False) + "\n").encode()
            if len(payload) > 2 * LIMIT:
                payload = (json.dumps({"id": request_id, "error": {"message": "context response exceeds limit"}}) + "\n").encode()
            connection.sendall(payload)
        except OSError:
            pass
        finally:
            connection.close()
            slots.release()

    def serve() -> None:
        server.settimeout(0.2)
        while not stopping.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            if not slots.acquire(blocking=False):
                connection.close()
                continue
            threading.Thread(target=handle, args=(connection,), daemon=True).start()

    listener = threading.Thread(target=serve, daemon=True)
    listener.start()
    child = subprocess.Popen(command, start_new_session=True)

    def terminate(signum: int, _frame: object) -> None:
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        return child.wait()
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stopping.set()
        # The listener thread times out and exits before this socket is closed.
        listener.join(timeout=1)
        server.close()
        endpoint.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
