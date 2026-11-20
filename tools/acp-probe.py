"""Check that an ACP agent starts and opens a session, and nothing more.

    python3 -I acp-probe.py CWD ARGV...

tools/agent-loop NAME acp probe runs this inside the worker's own sandbox, so a
coordinator's canary finds a broken adapter, a missing package or a lapsed login
before a worker meets it. It sends initialize and session/new and stops: no
prompt, so no model turn and no work. Prints ACP-PROBE-OK and what the agent
said it is, or ERROR and why, with the last lines the agent wrote.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from typing import Any

TIMEOUT = 60.0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("ERROR usage: acp-probe.py CWD ARGV...", file=sys.stderr)
        return 2
    cwd, command = argv[0], argv[1:]
    try:
        agent = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, bufsize=1)
    except OSError as error:
        print(f"ERROR the agent did not start: {error}", file=sys.stderr)
        return 1
    said: list[str] = []
    assert agent.stderr is not None
    reader = threading.Thread(target=lambda: said.extend(agent.stderr or []), daemon=True)
    reader.start()

    def fail(why: str) -> int:
        stop(agent)
        reader.join(2)
        tail = "".join(said[-15:]).rstrip()
        print(f"ERROR {why}" + (f"\n{tail}" if tail else ""), file=sys.stderr)
        return 1

    hello = call(agent, 1, "initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    if "error" in hello:
        return fail(f"initialize: {describe(hello['error'])}")
    made = call(agent, 2, "session/new", {"cwd": cwd, "mcpServers": []})
    if "error" in made:
        return fail(f"session/new: {describe(made['error'])}")
    info = (hello.get("result") or {}).get("agentInfo") or {}
    model = ((made.get("result") or {}).get("models") or {}).get("currentModelId") or ""
    stop(agent)
    print("ACP-PROBE-OK " + " ".join(str(v) for v in (info.get("name"), info.get("version"), model) if v))
    return 0


def call(agent: subprocess.Popen[str], number: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """One request, answered or not within TIMEOUT; requests the agent makes are refused."""
    assert agent.stdin is not None and agent.stdout is not None
    try:
        send(agent, {"jsonrpc": "2.0", "id": number, "method": method, "params": params})
    except OSError:
        return {"error": "the agent closed its input"}
    answer: dict[str, Any] = {"error": f"no answer within {TIMEOUT:.0f} seconds"}

    def read() -> None:
        nonlocal answer
        assert agent.stdout is not None
        for line in agent.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("id") == number and "method" not in message:
                answer = message
                return
            if "method" in message and "id" in message:
                try:
                    send(agent, {"jsonrpc": "2.0", "id": message["id"],
                                 "error": {"code": -32601, "message": "a probe answers nothing"}})
                except OSError:
                    break  # the agent is gone; its answer will not come
        answer = {"error": "the agent closed its output"}

    reading = threading.Thread(target=read, daemon=True)
    reading.start()
    reading.join(TIMEOUT)
    return answer


def send(agent: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert agent.stdin is not None
    agent.stdin.write(json.dumps(message) + "\n")
    agent.stdin.flush()


def describe(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(error)


def stop(agent: subprocess.Popen[str]) -> None:
    try:
        if agent.stdin is not None:
            agent.stdin.close()
    except OSError:
        pass
    end = time.monotonic() + 5
    while agent.poll() is None and time.monotonic() < end:
        time.sleep(0.05)
    if agent.poll() is None:
        agent.kill()
        agent.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
