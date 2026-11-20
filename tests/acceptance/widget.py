#!/usr/bin/env python3
"""Tests of record for the Ctrl+G widget in a real interactive bash and zsh on a pty (SPEC.md 6.4).

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
    def __init__(self, shell, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            if shell == "bash":
                os.execve(shutil.which("bash"), ["bash", "--norc", "--noprofile", "-i"], env)
            os.execve(shutil.which("zsh"), ["zsh", "-f", "-i"], env)
        self.buf = b""
        if shell == "bash":
            self.command(f"PS1='{MARK} '; HISTFILE=; set -o history")
        else:
            self.command(f"PROMPT='{MARK} '; unsetopt PROMPT_SP; HISTSIZE=50")
        self.command(f'eval "$({SOL} --init {shell})"')

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


def run(shell, answer, status, keys, expect, name, history=None):
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
            "LANG": "C.UTF-8",
            "INPUTRC": "/dev/null",
            "SOL_VAZHI": os.path.join(work, "vazhi"),
            "STUB_DIR": work,
            "STUB_ANSWER": answer,
            "STUB_STATUS": str(status),
        }
        sh = Shell(shell, env)
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
        check(f"{name} ({shell})", got, f"wanted {needle!r} in output: {output!r}")
        return called, args
    finally:
        shutil.rmtree(work, ignore_errors=True)


if not shutil.which("zsh"):
    check("zsh is installed for the zsh widget tests", False, "install zsh")

for shell in ("bash", "zsh"):
    if not shutil.which(shell):
        continue
    # REQ-WIDGET-02 (bash), REQ-WIDGET-05 (zsh): Ctrl+G puts the command on the line with the
    # cursor at its end, runs nothing, and sends recent history as context.
    called, args = run(shell, "```bash\nls -lS\n```", 0, "list files by size\x07", "ls -lS",
                       "REQ-WIDGET-02 REQ-WIDGET-05 line becomes the command, cursor at the end",
                       history=["true first-command", "true middle-command", "true latest-command"])
    system = args[3].decode() if len(args) > 3 else ""
    # The latest command too: inside bash's bind -x, fc -l would leave it out.
    check(f"REQ-WIDGET-02 REQ-WIDGET-05 history reaches sol, latest included ({shell})",
          "\n  true first-command\n  true middle-command\n  true latest-command" in system, system)

    # A command with non-ASCII text still leaves the cursor at its end.
    run(shell, "echo h\u00e9llo", 0, "say hello\x07", "echo h\u00e9llo",
        "REQ-WIDGET-02 REQ-WIDGET-05 cursor at the end of a UTF-8 command")

    # The widget sends the shell's aliases, so an aliased ls runs as the original.
    run(shell, "ls -lt", 0, "list newest\x07", "command ls -lt",
        "REQ-WIDGET-02 REQ-WIDGET-05 aliases reach sol", history=["alias ls='echo'"])

    # REQ-WIDGET-03: when no model answers, the request stays on the line unchanged.
    run(shell, "", 1, "list files by size\x07", "list files by size", "REQ-WIDGET-03 failure leaves the line")

    # REQ-WIDGET-04: Ctrl+G on a blank line asks nothing.
    called, _ = run(shell, "ls", 0, "   \x07", "", "REQ-WIDGET-04 blank line stays")
    check(f"REQ-WIDGET-04 vazhi not called for a blank line ({shell})", not called)

# bash only: a command spanning lines in history is one entry, its number stripped.
called, args = run("bash", "ls", 0, "list\x07", "ls", "REQ-WIDGET-02 multi-line history",
                   history=["echo 'two\nlines'"])
system = args[3].decode() if len(args) > 3 else ""
check("REQ-WIDGET-02 multi-line history entry joined (bash)", "\n  echo 'two lines'" in system, system)

if failures:
    print(f"ERROR {failures} widget test(s) failed; see the FAIL lines above")
    sys.exit(1)
print("all widget tests passed")
