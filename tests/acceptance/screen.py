#!/usr/bin/env python3
"""Tests of record for what the widget shows on screen (SPEC.md REQ-WIDGET-06), in bash and zsh.

A real interactive shell runs on a pty behind a pyte terminal of 60x10, so the test sees the
screen a person would. vazhi is a stub that answers after a second. Run with pyte available:
    uv run --no-project --with pyte==0.8.2 python tests/acceptance/screen.py
"""
import fcntl
import os
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time

import pyte

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOL = os.path.join(ROOT, "sol")
ROWS, COLS = 10, 60
STUB = """#!/usr/bin/env bash
sleep "${STUB_DELAY:-1}"
[ "${STUB_STATUS:-0}" = 0 ] || { echo "vazhi: every model failed" >&2; exit "$STUB_STATUS"; }
printf '%s' "$STUB_ANSWER"
"""
failures = 0


def check(name, ok, screen_text=""):
    global failures
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures += 1
        print("     screen:\n" + "\n".join("     |" + line for line in screen_text.splitlines()))


class Term:
    def __init__(self, shell, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            argv = ["bash", "--norc", "--noprofile", "-i"] if shell == "bash" else ["zsh", "-f", "-i"]
            os.execve(shutil.which(shell), argv, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.screen = pyte.Screen(COLS, ROWS)
        self.stream = pyte.ByteStream(self.screen)
        self.pump(0.5)
        setup = "PS1='$ '; HISTFILE=" if shell == "bash" else "PROMPT='$ '; unsetopt PROMPT_SP"
        for line in (setup, f'eval "$({SOL} --init {shell})"', "clear"):
            self.type(line + "\n", 0.4)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.03)
            if ready:
                try:
                    self.stream.feed(os.read(self.fd, 65536))
                except OSError:
                    return

    def type(self, text, settle=0.3):
        os.write(self.fd, text.encode())
        self.pump(settle)

    def text(self):
        return "\n".join(line.rstrip() for line in self.screen.display).rstrip()

    def close(self):
        try:
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def scenario(shell, answer, status):
    work = tempfile.mkdtemp()
    try:
        stub = os.path.join(work, "vazhi")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": work, "TERM": "xterm",
               "LANG": "C.UTF-8", "INPUTRC": "/dev/null", "SOL_VAZHI": stub,
               "STUB_ANSWER": answer, "STUB_STATUS": str(status), "STUB_DELAY": "1"}
        term = Term(shell, env)
        term.type("list files by size")
        term.type("\x07", 0.5)
        during = term.text()
        term.pump(1.5)
        after = term.text()
        term.type(" Z", 0.3)
        typed = term.text()
        term.close()
        return during, after, typed
    finally:
        shutil.rmtree(work, ignore_errors=True)


for shell in ("bash", "zsh"):
    if not shutil.which(shell):
        check(f"{shell} is installed", False)
        continue
    during, after, typed = scenario(shell, "ls -lS", 0)
    check(f"REQ-WIDGET-06 a spinner with the time shows while sol waits ({shell})",
          "sol: thinking 0." in during, during)
    check(f"REQ-WIDGET-06 the spinner is gone and the line holds the command ({shell})",
          "thinking" not in after and after.splitlines()[-1] == "$ ls -lS", after)
    check(f"REQ-WIDGET-06 typing continues at the end of the command ({shell})",
          typed.splitlines()[-1] == "$ ls -lS Z", typed)

    during, after, typed = scenario(shell, "", 1)
    lines = after.splitlines()
    check(f"REQ-WIDGET-06 on failure the reason stays on screen ({shell})",
          "vazhi: every model failed" in after and "thinking" not in after, after)
    check(f"REQ-WIDGET-06 on failure the request is still on the line ({shell})",
          any(line == "$ list files by size" for line in lines), after)
    check(f"REQ-WIDGET-06 on failure typing continues at the end of the request ({shell})",
          "$ list files by size Z" in typed, typed)

if failures:
    print(f"ERROR {failures} screen test(s) failed; see the FAIL lines above")
    sys.exit(1)
print("all screen tests passed")
