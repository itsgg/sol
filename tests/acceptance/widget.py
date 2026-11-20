#!/usr/bin/env python3
"""Tests of record for the Ctrl+G widget in a real interactive bash on a pty (SPEC.md 6.3).

vazhi is a stub, so nothing touches the network. Each test types a request, presses Ctrl+G,
then types more and checks what the line became by echoing it, which also shows nothing ran
before Enter. Usage: tests/acceptance/widget.py
"""
import os
import pty
import select
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOL = os.path.join(ROOT, "sol")
MARK = "@@"

STUB = """#!/usr/bin/env bash
for a in "$@"; do printf '%s\\0' "$a"; done > "$STUB_DIR/args"
touch "$STUB_DIR/called"
[ "${STUB_STATUS:-0}" = 0 ] || { echo "vazhi: no model answered" >&2; exit "$STUB_STATUS"; }
printf '%s' "$STUB_ANSWER"
"""


class Shell:
    def __init__(self, work, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execve("/bin/bash", ["bash", "--norc", "--noprofile", "-i"], env)
        self.buf = b""
        self.command(f"PS1='{MARK} '; HISTFILE=; set -o history")
        self.command(f'eval "$({SOL} --init bash)"')

    def command(self, line):
        """Run one line and wait for the next prompt: readline flushes input typed ahead of it."""
        self.buf = b""
        self.send(line + "\n")
        end = time.time() + 3
        while time.time() < end and not self.buf.rstrip().endswith(MARK.encode()):
            self.read(0.05)

    def send(self, text):
        os.write(self.fd, text.encode())

    def read(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if ready:
                try:
                    self.buf += os.read(self.fd, 4096)
                except OSError:
                    break

    def wait_for(self, needle, seconds):
        end = time.time() + seconds
        while time.time() < end and needle not in self.buf:
            self.read(0.1)
        return needle in self.buf

    def close(self):
        self.send("exit\n")
        self.read(0.3)
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


failures = 0


def check(name, ok, detail=""):
    global failures
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    failures += 0 if ok else 1


def run(answer, status, keys, expect, name, history=None):
    """Type keys in a fresh shell (Ctrl+G is \\x07); after them type ' Z', go to the start,
    insert 'echo ' and press Enter, so the output is the final line."""
    work = tempfile.mkdtemp()
    try:
        with open(os.path.join(work, "vazhi"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(work, "vazhi"), 0o755)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": work,
            "TERM": "dumb",
            "INPUTRC": "/dev/null",
            "SOL_VAZHI": os.path.join(work, "vazhi"),
            "STUB_DIR": work,
            "STUB_ANSWER": answer,
            "STUB_STATUS": str(status),
        }
        sh = Shell(work, env)
        for line in history or []:
            sh.command(line)
        sh.buf = b""
        sh.send(keys)
        sh.read(0.8)
        sh.send(" Z\x01echo \n")
        needle = f"\n{expect} Z" if expect else "\nZ"
        got = sh.wait_for(needle.encode(), 3)
        called = os.path.exists(os.path.join(work, "called"))
        args = open(os.path.join(work, "args"), "rb").read().split(b"\0") if called else []
        output = sh.buf.decode(errors="replace")
        sh.close()
        check(name, got, f"wanted {needle!r} in output: {output!r}")
        return called, args
    finally:
        shutil.rmtree(work, ignore_errors=True)


# REQ-WIDGET-02: Ctrl+G puts the command on the line with the cursor at its end, runs nothing,
# and sends recent history as context.
called, args = run("```bash\nls -lS\n```", 0, "list files by size\x07", "ls -lS",
                   "REQ-WIDGET-02 line becomes the command, cursor at the end",
                   history=["true first-command", "echo 'two\nlines'", "true latest-command"])
system = args[3].decode() if len(args) > 3 else ""
# The latest command too: inside bind -x, fc -l would leave it out.
check("REQ-WIDGET-02 history reaches sol, latest included, numbers stripped",
      "\n  true first-command\n  echo 'two lines'\n  true latest-command" in system, system)

# REQ-WIDGET-03: when no model answers, the request stays on the line unchanged.
run("", 1, "list files by size\x07", "list files by size", "REQ-WIDGET-03 failure leaves the line")

# REQ-WIDGET-04: Ctrl+G on a blank line asks nothing.
called, _ = run("ls", 0, "   \x07", "", "REQ-WIDGET-04 blank line stays")
check("REQ-WIDGET-04 vazhi not called for a blank line", not called)

if failures:
    print(f"ERROR {failures} widget test(s) failed; see the FAIL lines above")
    sys.exit(1)
print("all widget tests passed")
