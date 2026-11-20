"""The gate's checks and the hooks' logic, standard library only.

Run as `python3 -I tools/checks.py <check> [args]`. Each check prints what it
found and exits non-zero on a failure; an ERROR line says what to do. The
checks hold the rules AGENTS.md states, so a rule there names its check here.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

# CHECKS_ROOT lets the template repository run a check over its own files.
ROOT = Path(os.environ.get("CHECKS_ROOT") or Path(__file__).resolve().parent.parent)
# The tools this copy came with: its settings judge the tree at ROOT, which
# tools/gate points at a branch when main's gate judges it.
HARNESS = Path(__file__).resolve().parent
MAIN = "main"

# Commit messages (rules.md, Git and Writing style).
SCISSORS = "# ------------------------ >8 ------------------------"
NAMED = r"(?:cursor|claude|fable|codex|sonnet|opus|haiku|gpt[\w.-]*|gemini|copilot|agy|ai)"
ACTOR = rf"(?:{NAMED}|(?:an?|the)\s+(?:agent|reviewer|model|llm|bot)|agents?|reviewers?)"
DONE = r"(?:written|authored|built|generated|drafted|assisted|made|created)"
CREDITS = (
    r"(?im)^\W*reviewed\s+by\b",
    r"(?im)^\W*review(?:ers?|s)?\s*:\s*(?!none\b|pending\b|n/?a\b)\S",
    r"(?im)\breview(?:ed)?\s+by\s+(?!hand\b|the\s+gate\b)\S",
    r"(?im)\breviewed\s+(?:it|this|the\s+(?:diff|change|commit|branch|patch|pull request))\b",
    rf"(?im)^\W*{DONE}\s+(?:by|with)\s+{ACTOR}\b",
    rf"(?im)\b(?:was|were|been)\s+{DONE}\s+(?:by|with)\s+{ACTOR}\b",
)
TRAILER = (
    r"(?im)^(?:[\w-]*(?:author|assist|generated?|review|help)[\w-]*-by|claude-session|made-with)\s*:"
    rf"|^[\w-]+-by\s*:[^\n]*\b{ACTOR}\b"
    r"|^\W*generated with \[?claude"
)
CONVENTIONAL = re.compile(
    r"^(?:feat|fix|test|docs|refactor|chore|build|ci|perf|style|revert)(?:\([a-z0-9./-]+\))?!?: \S"
)
IMPERATIVE = re.compile(r"^[A-Z][a-z]+(?:\s|$)")
DECLARED_PROTECTED = re.compile(r"(?m)^Protected:\s*(\S+?)\s*:\s*\S")
# A test's name runs to the first colon: a bun or Jest test is named in words.
DECLARED_REMOVED = re.compile(r"(?m)^Removes test:\s*(.+?)\s*:\s*\S")
DECLARED_MODIFIED = re.compile(r"(?m)^Modifies test:\s*(.+?)\s*:\s*\S")

SECRETS = (
    (r"sk-ant-[a-z0-9]+-[A-Za-z0-9_\-]{40,}", "Anthropic key"),
    (r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}", "OpenAI key"),
    (r"\bAIza[0-9A-Za-z\-_]{35}\b", "Google API key"),
    (r"\b\d{8,11}:[A-Za-z0-9_\-]{35}\b", "Telegram bot token"),
    (r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{60,}\b", "GitHub token"),
    (r"\bglpat-[A-Za-z0-9_\-]{20,}\b", "GitLab token"),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----", "private key"),
)

REQ = re.compile(r"\bREQ-[A-Z][A-Z0-9]*-\d+\b")
REQ_DEFINED = re.compile(r"(?m)^#{2,4}\s+(REQ-[A-Z][A-Z0-9]*-\d+)\b")
TASK_FILE = re.compile(r"^tasks/(\d{4})-[a-z0-9-]+\.md$")
TASK_STATUSES = {"open", "claimed", "review", "blocked", "done"}
TEXT_LIMIT = 2_000_000


class Fail(Exception):
    """A check failed; the message is printed after ERROR."""


def git(*args: str, check: bool = True, cwd: Path | None = None) -> str:
    """Run git in the repository and return its output."""
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], cwd=cwd or ROOT, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise Fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def gate_conf() -> dict[str, str]:
    """Read tools/gate.conf, then tools/gate.local.conf over it: shell files of NAME=value lines.

    They are this copy's, next to it, so main's settings judge a branch."""
    conf: dict[str, str] = {}
    for name in ("gate.conf", "gate.local.conf"):
        path = HARNESS / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
                if m:
                    conf[m.group(1)] = m.group(2).strip().strip("\"'")
    return conf


def files_listed(*args: str) -> list[str]:
    """Paths from a git listing command, read NUL-separated so no name is mangled."""
    split = args.index("--") if "--" in args else len(args)
    return [path for path in git(*args[:split], "-z", *args[split:]).split("\0") if path]


def tracked_and_new() -> list[str]:
    """Every file git tracks or would track: tracked plus untracked, not ignored."""
    return sorted(set(files_listed("ls-files", "--cached", "--others", "--exclude-standard")))


def read_text(path: Path) -> str | None:
    """A file's text, or None when it is missing, binary or too large."""
    try:
        if not path.is_file() or path.stat().st_size > TEXT_LIMIT:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def show(rev: str, path: str) -> str | None:
    """A file's text at a revision (":" for the index), or None if it was not there."""
    spec = f":{path}" if rev == ":" else f"{rev}:{path}"
    result = subprocess.run(["git", "show", spec], cwd=ROOT, capture_output=True, check=False)
    if result.returncode != 0 or b"\0" in result.stdout:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD").strip()


def branch_name() -> str:
    """The branch whose work is checked: the one tools/land names in
    GATE_BRANCH, a pull request's head on CI, else HEAD's ("HEAD" when detached)."""
    named = os.environ.get("GATE_BRANCH", "").strip()
    if named:
        return named
    if os.environ.get("GATE_CI"):
        ci = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
        if ci:
            return ci
    return branch() if ref_exists("HEAD") else "HEAD"


def test_edits_declared() -> bool:
    """Whether an edit to an existing test needs a 'Modifies test:' line here:
    always, unless tools/gate.local.conf sets TEST_EDITS=agents, and then on
    agent/* branches and on any branch the checks cannot name."""
    if gate_conf().get("TEST_EDITS", "all") != "agents":
        return True
    name = branch_name()
    return name == "HEAD" or name.startswith("agent/")


def ref_exists(ref: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "-q", "--verify", ref], cwd=ROOT, capture_output=True, check=False
    ).returncode == 0


def base() -> str | None:
    """Where this branch's own commits start; None means the whole history.

    On a branch, its merge base with main (or origin/main); on main, with its
    upstream; with neither, every commit is checked. CI passes the pushed
    range's start in GATE_BASE, or the pull request's target."""
    # Pull request synchronize events also carry `before`, which can name
    # an unavailable pre-rebase commit. Their target defines the range.
    pull_request = os.environ.get("GATE_CI") and os.environ.get("GITHUB_BASE_REF")
    env = "" if pull_request else os.environ.get("GATE_BASE", "").strip()
    if env:
        if set(env) <= {"0"} or not ref_exists(f"{env}^{{commit}}"):
            return None
        return git("rev-parse", env).strip()
    if os.environ.get("GATE_CI"):
        target = os.environ.get("GITHUB_BASE_REF")
        if target and ref_exists(f"refs/remotes/origin/{target}"):
            return git("merge-base", "HEAD", f"refs/remotes/origin/{target}").strip()
        return None
    if not ref_exists("HEAD"):
        return None
    if branch() != MAIN:
        for ref in (f"refs/heads/{MAIN}", f"refs/remotes/origin/{MAIN}"):
            if ref_exists(ref):
                return git("merge-base", "HEAD", ref).strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "@{upstream}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    if upstream:
        return git("merge-base", "HEAD", upstream).strip()
    return None


@dataclass
class Commit:
    sha: str
    parent: str | None
    files: list[str]
    message: str


def commits(since: str | None, head: str = "HEAD") -> list[Commit]:
    """The non-merge commits in since..head (all of head's history when None), oldest first."""
    if not ref_exists(head):
        return []
    spec = [f"{since}..{head}"] if since else [head]
    out = git("log", "--no-merges", "--reverse", "--no-renames", "--format=%x1e%H%x1f%P%x1f%B%x1f", "--name-only", *spec)
    found = []
    for record in out.split("\x1e")[1:]:
        sha, parents, message, rest = record.split("\x1f", 3)
        files = [line for line in rest.splitlines() if line.strip()]
        found.append(Commit(sha.strip(), parents.split()[0] if parents.split() else None, files, message))
    return found


def uncommitted_changes() -> list[str]:
    if not ref_exists("HEAD"):
        return tracked_and_new()
    changed = set(files_listed("diff", "--name-only", "--no-renames", "HEAD"))
    changed |= set(files_listed("ls-files", "--others", "--exclude-standard"))
    return sorted(changed)


def staged_changes() -> list[str]:
    return files_listed("diff", "--cached", "--name-only", "--no-renames")


def worktree_text(path: str) -> str | None:
    return read_text(ROOT / path)


def head_text(path: str) -> str | None:
    return show("HEAD", path)


def index_text(path: str) -> str | None:
    return show(":", path)


Reader = Callable[[str], "str | None"]


# Protected paths.

# Protected whatever tools/protected.txt says, so emptying that file in the
# same change protects nothing less.
FLOOR = (
    "SEED.md", "SPEC.md", "tools/**", ".githooks/**", ".claude/settings.json",
    ".github/workflows/**", ".copier-answers.yml", "tests/acceptance/**", "spec/cases/**",
)


def parse_patterns(text: str | None) -> set[str]:
    out = set()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def protected_patterns(*revs: str | None) -> list[str]:
    """The floor, the working tree's list, and the list at each given revision."""
    patterns = set(FLOOR) | parse_patterns(read_text(ROOT / "tools" / "protected.txt"))
    for rev in revs:
        if rev:
            patterns |= parse_patterns(show(rev, "tools/protected.txt"))
    return sorted(patterns)


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A path glob: * and ? stay within one segment, ** crosses segments, and
    dir/** is everything under the directory (research/*/** works). The paths
    matched are files; hook_pre_tool also asks about "dir/" for a command
    that names a directory."""
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$")


def matches(pattern: str, path: str) -> bool:
    return glob_regex(pattern).match(path) is not None


def is_protected(path: str, patterns: list[str]) -> bool:
    return any(matches(p, path) for p in patterns)


def acceptance_block(text: str | None) -> str | None:
    """The Acceptance section of a task file, which only the coordinator may change."""
    if text is None:
        return None
    m = re.search(r"(?ms)^Acceptance:\s*\n?(.*?)(?=^## |^[A-Z][a-z]+( [a-z]+)*: |\Z)", text)
    return m.group(1).strip() if m else ""


def protected_touched(paths: list[str], old: Reader | None, new: Reader, patterns: list[str]) -> list[str]:
    """Protected paths among `paths`, plus task files whose Acceptance changed."""
    touched = [p for p in paths if is_protected(p, patterns)]
    if old is not None:
        for p in paths:
            if TASK_FILE.match(p):
                before = old(p)
                if before is not None and acceptance_block(before) != acceptance_block(new(p)):
                    touched.append(f"{p}#acceptance")
    return sorted(set(touched))


def undeclared(touched: list[str], declared: list[str]) -> list[str]:
    return [t for t in touched if not any(matches(d, t) or d == "*" for d in declared)]


def committed_problems(since: str | None, head: str = "HEAD") -> list[str]:
    """Each commit in since..head declares, in its own message, the protected
    paths it changes and the tests it removes or edits. The patterns are the
    union of the working tree's, HEAD's, head's and since's lists, so a branch
    can add to the list but never shorten it."""
    patterns = protected_patterns("HEAD", head, since)
    edits = test_edits_declared()
    problems = []
    for c in commits(since, head):
        if c.parent is None:
            # The first commit founds the project (SEED.md alone); there is
            # nothing before it to weaken.
            continue
        at_commit = partial(show, c.sha)
        at_parent = partial(show, c.parent)
        for path in undeclared(protected_touched(c.files, at_parent, at_commit, patterns), DECLARED_PROTECTED.findall(c.message)):
            problems.append(f"{c.sha[:7]} changes {path} without a 'Protected: {path}: <why>' line in its message")
        for name in undeclared(removed_tests(c.files, at_parent, at_commit), DECLARED_REMOVED.findall(c.message)):
            problems.append(f"{c.sha[:7]} removes test {name} without a 'Removes test: {name}: <why>' line in its message")
        for name in undeclared(modified_tests(c.files, at_parent, at_commit) if edits else [], DECLARED_MODIFIED.findall(c.message)):
            problems.append(f"{c.sha[:7]} modifies test {name} without a 'Modifies test: {name}: <why>' line in its message")
    return problems


def check_declarations(argv: list[str]) -> None:
    """For landing: BASE..HEAD declares every protected change and every removed
    or edited test, judged by this checkout's checks and protected list, not
    the branch's own. Objects of an agent branch come through the alternate
    store tools/land exports."""
    if len(argv) != 2:
        raise Fail("declarations needs BASE and HEAD")
    for rev in argv:
        if not ref_exists(f"{rev}^{{commit}}"):
            raise Fail(f"{rev} is not a commit this repository can read")
    problems = committed_problems(git("rev-parse", argv[0]).strip(), git("rev-parse", argv[1]).strip())
    if problems:
        raise Fail("undeclared changes in " + argv[0] + ".." + argv[1] + ":\n  " + "\n  ".join(problems))
    print(f"declarations: every change in {argv[0]}..{argv[1]} is declared")


def check_protected() -> None:
    since = base()
    problems = [p for p in committed_problems(since) if " changes " in p]
    if not os.environ.get("GATE_IN_PRE_COMMIT"):
        old = head_text if ref_exists("HEAD") else None
        for path in protected_touched(uncommitted_changes(), old, worktree_text, protected_patterns("HEAD")):
            problems.append(f"{path} has an uncommitted change; revert it, or commit it with a 'Protected: {path}: <why>' line")
    if problems:
        raise Fail(
            "protected paths changed (tools/protected.txt). Weakening a check is never the fix; "
            "if the task needs this change, set the task to blocked and say why in its Log.\n  "
            + "\n  ".join(problems)
        )
    print(f"protected: every change since {since[:7] if since else 'the first commit'} is declared")


# Removed tests.

TEST_DIRS = {"tests", "test"}
JS_EXTENSIONS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
DEFINITIONS = {
    ".py": re.compile(r"(?m)^\s*(?:async\s+)?def\s+(test\w*)\s*\("),
    ".rs": re.compile(r"#\[(?:[\w:]+::)?test\]\s*(?:#\[[^\]]*\]\s*)*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
    ".go": re.compile(r"(?m)^func\s+((?:Test|Fuzz|Benchmark|Example)\w*)\s*\("),
    ".js": re.compile(r"""\b(?:it|test)\s*\(\s*(['"`])((?:(?!\1).)+)\1"""),
    ".qml": re.compile(r"(?m)^\s*function\s+(test_\w+)\s*\("),
}


def is_test_file(path: str) -> bool:
    """Where each language keeps tests, plus any file under a tests/ or test/
    directory, plus the TEST_GLOBS of tools/gate.local.conf."""
    parts = path.split("/")
    name = parts[-1]
    ext = os.path.splitext(name)[1]
    in_test_dir = any(part in TEST_DIRS for part in parts[:-1])
    if any(fnmatch.fnmatchcase(path, g) for g in gate_conf().get("TEST_GLOBS", "").split()):
        return True
    if ext == ".rs":
        return True
    if ext == ".go":
        return name.endswith("_test.go")
    if ext == ".qml":
        return name.startswith("tst_")
    if ext == ".py":
        return name.startswith("test_") or name.endswith("_test.py") or in_test_dir
    if ext in JS_EXTENSIONS:
        return bool(re.search(r"\.(?:test|spec)\.", name)) or in_test_dir
    return False


def test_names(path: str, text: str | None) -> list[str]:
    if text is None:
        return []
    ext = os.path.splitext(path)[1]
    pattern = DEFINITIONS[".js"] if ext in JS_EXTENSIONS else DEFINITIONS.get(ext)
    if pattern is None:
        return []
    return [f[-1] if isinstance(f, tuple) else f for f in pattern.findall(text)]


def removed_tests(paths: list[str], old_text: Reader, new_text: Reader) -> list[str]:
    old: Counter[str] = Counter()
    new: Counter[str] = Counter()
    for p in paths:
        if is_test_file(p):
            old.update(test_names(p, old_text(p)))
            new.update(test_names(p, new_text(p)))
    return sorted((old - new).elements())


def body_end(text: str, ext: str, start: int, def_end: int) -> int:
    """Where the test that starts at `start` ends: its closing brace in brace
    languages, the next line indented no deeper than its def in Python."""
    if ext == ".py":
        line_start = text.rfind("\n", 0, start) + 1
        indent = len(text[line_start:start]) - len(text[line_start:start].lstrip())
        pos = text.find("\n", def_end)
        while pos != -1:
            nxt = text.find("\n", pos + 1)
            line = text[pos + 1 : nxt if nxt != -1 else len(text)]
            if line.strip() and len(line) - len(line.lstrip()) <= indent and not line.lstrip().startswith((")", "]", "}")):
                return pos
            pos = nxt
        return len(text)
    brace = text.find("{", def_end)
    if brace == -1:
        return len(text)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def folded(body: str, ext: str) -> str:
    """A test body with what formatters change taken out: comments, whitespace,
    trailing commas and, outside Rust, the kind of quote."""
    comment = r"(?m)(?:^|\s)#.*$" if ext == ".py" else r"(?m)(?:^|\s)//.*$"
    body = re.sub(comment, "", body)
    body = re.sub(r"\s+", "", body)
    body = re.sub(r",(?=[)\]}])", "", body)
    if ext != ".rs":
        body = body.replace("'", '"')
    return body


def decorated_start(text: str, start: int) -> int:
    """The start of the decorators above a Python def at `start`, which belong
    to its test; a decorator may run over several lines."""
    lines = text[:start].split("\n")[:-1]
    def_line_start = text.rfind("\n", 0, start) + 1
    indent = start - def_line_start if text[def_line_start:start].strip() == "" else 0
    best = start
    offset = def_line_start
    for line in reversed(lines):
        offset -= len(line) + 1
        stripped = line.strip()
        if not stripped:
            break
        depth = len(line) - len(line.lstrip())
        if depth == indent and stripped.startswith("@"):
            best = offset
        elif depth > indent or stripped.startswith((")", "]", "}")):
            continue
        else:
            break
    return best


def test_bodies(path: str, text: str | None) -> dict[str, list[str]]:
    """Each test's body, folded, by name; tests sharing a name (the same it()
    title in two describe blocks) are kept in order."""
    if text is None:
        return {}
    ext = os.path.splitext(path)[1]
    pattern = DEFINITIONS[".js"] if ext in JS_EXTENSIONS else DEFINITIONS.get(ext)
    if pattern is None:
        return {}
    bodies: dict[str, list[str]] = {}
    for m in pattern.finditer(text):
        name = m.group(m.lastindex or 0)
        # The pattern's leading \s* may take blank lines; start at the keyword.
        keyword = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        start = decorated_start(text, keyword) if ext == ".py" else keyword
        end = body_end(text, ext, keyword, m.end())
        bodies.setdefault(name, []).append(folded(text[start:end], ext))
    return bodies


def modified_tests(paths: list[str], old_text: Reader, new_text: Reader) -> list[str]:
    """Tests that exist before and after a change with a different body: an
    assertion edited, a tolerance loosened, a case special-cased. Adding a
    test is free; a change to one that already passed needs saying why."""
    changed: set[str] = set()
    for p in paths:
        if is_test_file(p):
            before = test_bodies(p, old_text(p))
            after = test_bodies(p, new_text(p))
            # Same count under a name: compare in order. A different count is
            # a removal (removed_tests) or an addition (free).
            changed.update(
                name for name, bodies in before.items()
                if len(after.get(name, [])) == len(bodies) and after[name] != bodies
            )
    return sorted(changed)


def check_tests_removed() -> None:
    since = base()
    problems = [p for p in committed_problems(since) if " removes test " in p or " modifies test " in p]
    if not os.environ.get("GATE_IN_PRE_COMMIT") and ref_exists("HEAD"):
        changes = uncommitted_changes()
        for name in removed_tests(changes, head_text, worktree_text):
            problems.append(f"test {name} removed in uncommitted work; restore it, or commit with a 'Removes test: {name}: <why>' line")
        for name in modified_tests(changes, head_text, worktree_text) if test_edits_declared() else []:
            problems.append(f"test {name} changed in uncommitted work; restore it, or commit with a 'Modifies test: {name}: <why>' line")
    if problems:
        raise Fail("tests disappeared or changed. Deleting, renaming or editing a test to pass is never the fix.\n  " + "\n  ".join(problems))
    print("tests-removed: none undeclared")


GUARDED_DIRS = {"tasks", "tests", "test", "spec", "tools", ".githooks"}


def check_symlinks() -> None:
    """Task, test, spec and tool files are regular files, so what a check reads
    is what a change to that path changes."""
    found = [rel for rel in tracked_and_new() if rel.split("/")[0] in GUARDED_DIRS and (ROOT / rel).is_symlink()]
    if found:
        raise Fail("symbolic links where checks read files; replace them with the files: " + ", ".join(found))
    print("symlinks: none in guarded directories")


# Commit messages.

def message_problems(message: str, style: str) -> list[str]:
    message = re.split(rf"(?m)^{re.escape(SCISSORS)}$", message, maxsplit=1)[0]
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    prose = "\n".join(lines)
    found: list[str] = []
    if not lines or not lines[0].strip():
        return ["an empty subject"]
    subject = lines[0]
    if subject.startswith(("Merge ", "fixup! ", "squash! ", "amend! ")):
        return found
    if not prose.isascii():
        found.append("a non-ASCII character (an em dash, a curly quote, an arrow)")
    if re.search(r"\S - \S", prose):
        found.append("a spaced hyphen used as a dash")
    if len(lines) > 1 and lines[1].strip():
        found.append("no blank line after the subject")
    if re.search(TRAILER, message):
        found.append("an attribution trailer")
    elif any(re.search(pattern, message) for pattern in CREDITS):
        found.append("a line crediting the change or its review to an agent, a model or a reviewer")
    if style == "conventional" and not CONVENTIONAL.match(subject):
        found.append("a subject that is not Conventional Commits (feat:, fix:, test:, docs:, refactor:, chore:, ...)")
    if style == "imperative" and (not IMPERATIVE.match(subject) or CONVENTIONAL.match(subject)):
        found.append("a subject that is not an imperative sentence starting with a capital (Add ..., Fix ...)")
    if subject.endswith("."):
        found.append("a full stop at the end of the subject")
    return found


def check_commit_msg(argv: list[str]) -> None:
    if not argv:
        raise Fail("commit-msg needs the message file")
    message = Path(argv[0]).read_text(encoding="utf-8")
    style = gate_conf().get("SUBJECT_STYLE", "conventional")
    found = message_problems(message, style)
    staged = staged_changes()
    has_head = ref_exists("HEAD")
    patterns = protected_patterns("HEAD" if has_head else None, ":")
    touched = protected_touched(staged, head_text if has_head else None, index_text, patterns)
    for path in undeclared(touched, DECLARED_PROTECTED.findall(message)):
        found.append(f"a change to protected {path} without a 'Protected: {path}: <why>' line")
    if has_head:
        gone = removed_tests(staged, head_text, index_text)
        for name in undeclared(gone, DECLARED_REMOVED.findall(message)):
            found.append(f"a removed test {name} without a 'Removes test: {name}: <why>' line")
        edited_tests = modified_tests(staged, head_text, index_text) if test_edits_declared() else []
        for name in undeclared(edited_tests, DECLARED_MODIFIED.findall(message)):
            found.append(f"an edited test {name} without a 'Modifies test: {name}: <why>' line")
    if found:
        raise Fail("commit message: " + "\n  commit message: ".join(found))


# Repository hygiene.

def check_hooks() -> None:
    if os.environ.get("GATE_CI"):
        print("hooks: skipped on CI")
        return
    local = git("config", "--local", "--get", "core.hooksPath", check=False).strip()
    if local:
        raise Fail(f"a local core.hooksPath ({local}) hides the hooks; run: git config --local --unset core.hooksPath")
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    missing = []
    for hook in sorted((ROOT / ".githooks").glob("*")):
        shim = common / "hooks" / hook.name
        if read_text(shim) != hook_shim(hook.name) or not os.access(shim, os.X_OK):
            missing.append(hook.name)
    if missing:
        raise Fail(f"hooks not installed: {', '.join(missing)}; run: tools/install-hooks")
    # With a global core.hooksPath, ask git to run each hook as a commit
    # would, with a one-time token, and expect this repository's hook to echo
    # it: a hooks path that forgets to dispatch here is caught. It catches a
    # misconfiguration, not a hook written to answer the probe.
    effective = git("config", "--get", "core.hooksPath", check=False).strip()
    if effective:
        probe_hooks(effective)
    print("hooks: installed")


def probe_hooks(effective: str) -> None:
    gate_dir = ROOT / ".gate"
    gate_dir.mkdir(exist_ok=True)
    token = hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    token_file, message = gate_dir / "hook-probe-token", gate_dir / "hook-probe-msg"
    token_file.write_text(token, encoding="utf-8")
    message.write_text("chore: probe\n", encoding="utf-8")
    timeout = int(os.environ.get("HOOK_PROBE_TIMEOUT", "30"))
    try:
        for hook in sorted((ROOT / ".githooks").glob("*")):
            args = ["--", str(message)] if hook.name == "commit-msg" else []
            try:
                ran = subprocess.run(
                    ["git", "hook", "run", "--ignore-missing", hook.name, *args], cwd=ROOT,
                    env={**os.environ, "GATE_HOOK_PROBE": token}, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, check=False, timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise Fail(f"core.hooksPath is {effective}, and its {hook.name} did not finish in {timeout}s") from e
            if "is not a git command" in ran.stderr:
                print(f"hooks: git has no `git hook run`, so whether {effective} dispatches here is not checked")
                return
            if ran.returncode != 0 or f"{HOOK_PROBE_ANSWER} {token}" not in ran.stdout + ran.stderr:
                raise Fail(
                    f"core.hooksPath is {effective}, and it does not run this repository's {hook.name} hook "
                    f"(exit {ran.returncode}); make it dispatch to $(git rev-parse --git-common-dir)/hooks, "
                    "or unset it, then run tools/install-hooks"
                )
    finally:
        token_file.unlink(missing_ok=True)
        message.unlink(missing_ok=True)


HOOK_PROBE_ANSWER = "vithai-hook-probe-ok"


def hook_shim(name: str) -> str:
    """What tools/install-hooks writes into .git/hooks: run the worktree's own
    copy, so a sandboxed worktree that cannot see the main checkout runs its hooks."""
    return (
        "#!/bin/sh\n"
        "# Installed by tools/install-hooks; runs this worktree's .githooks copy.\n"
        f'exec "$(git rev-parse --show-toplevel)/.githooks/{name}" "$@"\n'
    )


def check_conflicts() -> None:
    marker = re.compile(r"(?m)^(?:<{7}|>{7})(?: |$)")
    found = []
    for rel in tracked_and_new():
        text = read_text(ROOT / rel)
        if text and marker.search(text):
            found.append(rel)
    if found:
        raise Fail("merge conflict markers left in: " + ", ".join(found))
    print("conflicts: none")


def prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Lines of markdown outside fenced code, with inline code removed."""
    fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if not fence:
            yield number, re.sub(r"`[^`]*`", "", line)


def odd_character(line: str) -> str | None:
    """The first non-ASCII character that is not a letter or an accent: a
    dash, a curly quote, an arrow, an emoji. A name keeps its spelling."""
    for ch in line:
        if not ch.isascii() and unicodedata.category(ch) not in NAME_CATEGORIES:
            return ch
    return None


# Letters and accents; not Lm, the modifier letters, which hold look-alike
# apostrophes and quotes (U+02BC).
NAME_CATEGORIES = {"Lu", "Ll", "Lt", "Lo", "Mn", "Mc"}


def check_prose() -> None:
    excluded = gate_conf().get("PROSE_EXCLUDE", "").split()
    found = []
    for rel in tracked_and_new():
        if not rel.endswith(".md") or rel.startswith(("node_modules/", ".venv/")):
            continue
        if any(matches(g, rel) for g in excluded):
            continue
        text = read_text(ROOT / rel)
        if text is None:
            continue
        for number, line in prose_lines(text):
            odd = odd_character(line)
            if odd is not None:
                found.append(f"{rel}:{number}: {unicodedata.name(odd, 'a non-ASCII character').lower()}")
            elif re.search(r"\S - \S", line):
                found.append(f"{rel}:{number}: a spaced hyphen used as a dash")
    if found:
        raise Fail("prose is plain ASCII with no dash stand-ins:\n  " + "\n  ".join(found[:40]))
    print(f"prose: plain{', ' + str(len(excluded)) + ' pattern(s) excluded' if excluded else ''}")


def check_secrets(argv: list[str]) -> None:
    every = "--all" in argv
    since = base()
    if every or since is None:
        paths = tracked_and_new()
    else:
        changed = {f for c in commits(since) for f in c.files} | set(uncommitted_changes())
        paths = sorted(p for p in changed if (ROOT / p).exists())
    found = []
    for rel in paths:
        text = read_text(ROOT / rel)
        if text is None:
            continue
        for pattern, label in SECRETS:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                found.append(f"{rel}:{line}: {label}")
    if not every and shutil.which("betterleaks"):
        found.extend(scanner_findings(paths))
    if every and since is not None and shutil.which("betterleaks"):
        # The lines the branch adds, read inside hunks only so a line whose
        # text starts with "++" is kept: a removed secret is the fix, not a finding.
        added: list[str] = []
        in_hunk = False
        for row in git("diff", since).splitlines():
            if row.startswith("diff --git "):
                in_hunk = False
            elif row.startswith("@@"):
                in_hunk = True
            elif in_hunk and row.startswith("+"):
                added.append(row[1:])
        result = subprocess.run(
            ["betterleaks", "stdin", "--no-banner", "--redact"], input="\n".join(added),
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            found.append("betterleaks found a secret in the branch diff:\n" + result.stdout[-2000:])
    if found:
        raise Fail("possible secrets; remove them and rotate any that were real:\n  " + "\n  ".join(found))
    print(f"secrets: none in {len(paths)} file(s)")


def scanner_findings(paths: list[str]) -> list[str]:
    """betterleaks over the given files in one pass, each finding mapped back
    to its file and line; its few hundred rules sit on top of the regexes."""
    chunks: list[str] = []
    starts: list[tuple[int, str]] = []
    line = 1
    for rel in paths:
        text = read_text(ROOT / rel)
        if not text:
            continue
        if not text.endswith("\n"):
            text += "\n"
        starts.append((line, rel))
        chunks.append(text)
        line += text.count("\n")
    if not chunks:
        return []
    result = subprocess.run(
        ["betterleaks", "stdin", "--no-banner", "--redact", "-l", "error", "-f", "json", "-r", "-"],
        input="".join(chunks), capture_output=True, text=True, check=False,
    )
    # 0 is clean and 1 is leaks found, each with a JSON report; anything else,
    # or no report, means the scan did not happen.
    try:
        items = json.loads(result.stdout) if result.returncode in (0, 1) else None
    except json.JSONDecodeError:
        items = None
    if not isinstance(items, list) or (result.returncode == 1 and not items):
        return [f"betterleaks did not finish a scan (exit {result.returncode}): {result.stderr.strip()[-200:]}"]
    out = []
    for item in items:
        number = int(item.get("StartLine", 0))
        first, rel = max((s for s in starts if s[0] <= number), default=(1, "?"))
        out.append(f"{rel}:{number - first + 1}: {item.get('RuleID', 'a secret')} (betterleaks)")
    return out


def check_agents_md() -> None:
    path = ROOT / "AGENTS.md"
    if not path.exists():
        raise Fail("AGENTS.md is missing")
    text = path.read_text(encoding="utf-8")
    limit = int(gate_conf().get("AGENTS_MD_MAX_LINES", "150"))
    count = len(text.splitlines())
    problems = []
    if count > limit:
        problems.append(f"AGENTS.md has {count} lines; keep it under {limit} and move rules into checks")
    section = re.search(r"(?ms)^## Commands\s*$(.*?)(?=^## |\Z)", text)
    commands = re.findall(r"(?m)^\s*-\s*`([^`]+)`", section.group(1)) if section else []
    if not commands:
        problems.append("AGENTS.md has no '## Commands' section of '- `command`' lines")
    for command in commands:
        words = [w for w in command.split() if not re.match(r"^[A-Z_][A-Z0-9_]*=", w)]
        if not words:
            continue
        word = words[0]
        if "/" in word:
            target = ROOT / word
            if not target.exists() or not os.access(target, os.X_OK):
                problems.append(f"`{command}`: {word} is not an executable file")
        elif shutil.which(word) is None and word not in {"cd", "source", "."}:
            problems.append(f"`{command}`: {word} is not on PATH")
    if problems:
        raise Fail("AGENTS.md does not match the repository:\n  " + "\n  ".join(problems))
    print(f"agents-md: {len(commands)} command(s) exist, {count} lines")


# Spec traceability.

def spec_ids() -> tuple[set[str], set[str], list[str]]:
    """Live and retired requirement IDs in SPEC.md, and duplicate definitions."""
    text = read_text(ROOT / "SPEC.md") or ""
    live: list[str] = []
    retired: set[str] = set()
    in_retired = False
    for line in text.splitlines():
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            # Only a heading titled Retired lists retired IDs; a changelog under
            # "Changes and retired requirements" may name live ones.
            in_retired = re.match(r"(?:[\d.]+\s*)?retired\b", heading.group(2).strip(), re.IGNORECASE) is not None
            m = REQ_DEFINED.match(line)
            if m and not in_retired:
                live.append(m.group(1))
            continue
        if in_retired:
            retired.update(REQ.findall(line))
    dupes = sorted(i for i, n in Counter(live).items() if n > 1)
    return set(live), retired, dupes


@dataclass
class Task:
    status: str
    depends: list[str]
    spec: list[str]
    runs: list[str]


def parse_task(text: str) -> Task:
    def field(name: str) -> str:
        m = re.search(rf"(?m)^{name}:\s*(.*)$", text)
        return m.group(1).strip() if m else ""

    return Task(
        status=field("Status").lower(),
        depends=re.findall(r"\b\d{4}\b", field("Depends on")),
        spec=REQ.findall(field("Spec")),
        runs=re.findall(r"(?m)^\s*-\s*run:\s*`([^`]+)`", acceptance_block(text) or ""),
    )


def tasks() -> dict[str, tuple[str, Task]]:
    out = {}
    for rel in tracked_and_new():
        m = TASK_FILE.match(rel)
        if m:
            text = read_text(ROOT / rel) or ""
            out[m.group(1)] = (rel, parse_task(text))
    return out


def check_spec() -> None:
    if not (ROOT / "SPEC.md").exists():
        print("spec: no SPEC.md yet")
        return
    live, retired, dupes = spec_ids()
    problems = [f"{i} is defined more than once in SPEC.md" for i in dupes]
    skip = ("SPEC.md", "SEED.md", "AGENTS.md", "README.md")
    referenced: Counter[str] = Counter()
    for rel in tracked_and_new():
        if rel in skip or rel.startswith(("changes/", "tasks/", ".gate/")):
            continue
        text = read_text(ROOT / rel)
        if not text:
            continue
        for ref in set(REQ.findall(text)):
            if is_test_file(rel):
                referenced[ref] += 1
            if ref in retired:
                problems.append(f"{rel} cites {ref}, which SPEC.md retired")
            elif ref not in live:
                problems.append(f"{rel} cites {ref}, which SPEC.md does not define")
    for number, (rel, task) in sorted(tasks().items()):
        if task.status in {"review", "done"}:
            for ref in task.spec:
                if ref not in live:
                    problems.append(f"{rel} cites {ref}, which SPEC.md does not define")
                elif not referenced[ref]:
                    problems.append(f"{rel} is {task.status} but no test file cites {ref}")
    if problems:
        raise Fail("spec traceability:\n  " + "\n  ".join(problems))
    covered = sum(1 for i in live if referenced[i])
    print(f"spec: {len(live)} requirement(s), {covered} with tests, {len(retired)} retired")


# Characters that make a run line more than one program and its plain words.
SHELL_SYNTAX = re.compile(r"[;&|<>()$`\\*?!{}\[\]~'\"#\n]")


def batch_args(command: str, program: str) -> list[str] | None:
    """command's words after program, when it runs program with plain words only, else None.

    program may carry leading words (python3 -m unittest); its first word is a
    path, compared from the project root, so ./tests/x.sh and tests/x.sh match.
    """
    head = program.split()
    if not head or SHELL_SYNTAX.search(command):
        return None
    words = command.split()
    if len(words) < len(head) or words[1:len(head)] != head[1:]:
        return None
    if (ROOT / words[0]).resolve() != (ROOT / head[0]).resolve():
        return None
    return words[len(head):]


def run_acceptance(command: str) -> subprocess.CompletedProcess[str]:
    """One acceptance command in the project root; a timeout is a failure, not a crash.

    ACCEPTANCE_TIMEOUT in tools/gate.local.conf sets the seconds, 1800 by default.
    """
    limit = int(gate_conf().get("ACCEPTANCE_TIMEOUT", "1800") or 1800)
    try:
        return subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                              check=False, timeout=limit)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"timed out after {limit} s")


def check_tasks(argv: list[str]) -> None:
    run = "--run" in argv
    found = tasks()
    # A claim is a file in git's shared directory, seen by every worktree;
    # committed, it cost a pull request of its own and named the squash.
    problems = [f"{path}: a task lock is never committed; claim in $(git rev-parse --git-common-dir)/task-locks/"
                for path in tracked_and_new() if path.startswith("tasks/locks/")]
    for number, (rel, task) in sorted(found.items()):
        if task.status not in TASK_STATUSES:
            problems.append(f"{rel}: Status must be one of {', '.join(sorted(TASK_STATUSES))}")
        for dep in task.depends:
            if dep not in found:
                problems.append(f"{rel}: depends on {dep}, which has no task file")
        if task.status in {"review", "done"} and not task.runs:
            problems.append(f"{rel}: {task.status} with no '- run: `command`' line under Acceptance")
    if run:
        jobs = [(number, rel, task.status, command) for number, (rel, task) in sorted(found.items())
                if task.status in {"review", "done"} for command in task.runs]
        # ACCEPTANCE_BATCH names a program whose run lines may be one run with all
        # their words (a suite that checks each named requirement, then runs every
        # test): one run instead of one per task. If it fails, each line runs
        # alone, so the failure is still the task's.
        program = gate_conf().get("ACCEPTANCE_BATCH", "")
        batch = [(job, words) for job in jobs if (words := batch_args(job[3], program)) is not None]
        if len(batch) > 1:
            union = list(dict.fromkeys(word for _, words in batch for word in words))
            if run_acceptance(" ".join([program, *union])).returncode == 0:
                for (number, _, _, command), _ in batch:
                    print(f"tasks: {number} `{command}` passes (one run of {program} for {len(batch)})")
                done = {job[3] for job, _ in batch}
                jobs = [job for job in jobs if job[3] not in done]
            else:
                print(f"tasks: the one run of {program} failed; each task's line runs alone")
        for number, rel, status, command in jobs:
            result = run_acceptance(command)
            if result.returncode != 0:
                tail = (result.stdout + result.stderr).strip().splitlines()[-10:]
                problems.append(f"{rel} is {status} but `{command}` fails:\n    " + "\n    ".join(tail))
            else:
                print(f"tasks: {number} `{command}` passes")
    if problems:
        raise Fail("tasks:\n  " + "\n  ".join(problems))
    print(f"tasks: {len(found)} task file(s) well formed")


def check_manifest() -> None:
    path = ROOT / "manifest.json"
    if not path.exists():
        print("manifest: none")
        return
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Fail(f"manifest.json is not JSON: {e}") from e
    problems = []
    if m.get("schemaVersion") != 1:
        problems.append("schemaVersion must be the number 1")
    if not re.match(r"^io\.github\.[a-z0-9-]+\.[a-z0-9-]+$", str(m.get("id", ""))):
        problems.append("id must be io.github.<user>.<plugin>")
    for key in ("name", "version", "author", "description", "kinds", "entryPoints"):
        if not m.get(key):
            problems.append(f"missing {key}")
    if not re.match(r"^\d+\.\d+\.\d+$", str(m.get("version", ""))):
        problems.append("version must be semver")
    for kind, entry in (m.get("entryPoints") or {}).items():
        if not (ROOT / entry).exists():
            problems.append(f"entry point for {kind} is missing: {entry}")
    if problems:
        raise Fail("manifest.json: " + "; ".join(problems))
    print("manifest: ok")


# Reviewer output.

def stream_text(raw: str) -> str:
    """Join a reviewer's answer from stream-json output (Claude Code, agy or Codex).

    Plain lines (reconnect notices) are skipped; when the joined assistant
    text is longer than the final result, it wins."""
    texts: list[str] = []
    deltas: list[str] = []
    result = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
        elif event.get("type") == "result" and isinstance(event.get("result"), str):
            result = event["result"]
        elif event.get("event") == "step_update":
            step = event.get("step_update") or {}
            if step.get("step_type") == "agent_response" and step.get("text_delta"):
                deltas.append(step["text_delta"])
        elif event.get("event") == "result":
            response = (event.get("result") or {}).get("response")
            if isinstance(response, str):
                result = response
        elif event.get("type") == "item.completed":
            # Codex: its last message is the answer; earlier ones say what it will read.
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                result = item["text"]
    joined = "\n".join(t for t in texts if t.strip()) or "".join(deltas)
    return joined if len(joined.strip()) > len(result.strip()) else result


# Claude Code hooks.

def file_digest(path: Path) -> bytes:
    if not path.is_file():
        return b""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").digest()


def fingerprint() -> str:
    """What the gate's turn tier depends on: HEAD, every uncommitted change in
    full, and the installed hook shims."""
    h = hashlib.sha256()
    h.update(git("rev-parse", "HEAD", check=False).encode())
    h.update(git("diff", "HEAD", "--binary", check=False).encode())
    for rel in files_listed("ls-files", "--others", "--exclude-standard"):
        h.update(rel.encode() + b"\0" + file_digest(ROOT / rel))
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    for shim in sorted((common / "hooks").glob("*")):
        h.update(shim.name.encode() + b"\0" + file_digest(shim))
    return h.hexdigest()


def hook_stop() -> int:
    """Stop hook: run the turn gate when the tree changed since it last passed.

    A block decision sends Claude back to work with the failure; after three
    tries in a row on one session it lets the turn end, and the commit hook
    still holds. With STOP_HOOK=agents in tools/gate.local.conf it runs only
    on agent/* branches."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if gate_conf().get("STOP_HOOK", "always") == "agents" and not branch_name().startswith("agent/"):
        return 0
    state = ROOT / ".gate"
    state.mkdir(exist_ok=True)
    print_now = fingerprint()
    green = state / "last-green"
    if green.exists() and green.read_text().strip() == print_now:
        return 0
    session = re.sub(r"[^A-Za-z0-9-]", "", str(payload.get("session_id", "none")))[:64]
    tries_file = state / f"stop-{session}"
    tries = int(tries_file.read_text()) if tries_file.exists() and payload.get("stop_hook_active") else 0
    result = subprocess.run([str(ROOT / "tools" / "gate"), "--turn"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        green.write_text(fingerprint())
        tries_file.unlink(missing_ok=True)
        return 0
    if tries >= 3:
        tries_file.unlink(missing_ok=True)
        print("tools/gate --turn still fails after three tries; the commit hook will refuse a commit until it passes.", file=sys.stderr)
        return 0
    tries_file.write_text(str(tries + 1))
    tail = "\n".join(result.stdout.strip().splitlines()[-30:])
    # A block on stdout, not exit 2: Claude Code lets an exit-2 Stop hook
    # through as a non-blocking error when its stderr mentions a missing file,
    # and a failing test often does.
    print(json.dumps({"decision": "block", "reason": f"tools/gate --turn failed. Fix the cause, or set your task to blocked:\n{tail}"}))
    return 0


WRITES = re.compile(r"(?:>|\btee\b|\bsed\s+-[a-zA-Z]*i|\bperl\s+-[a-zA-Z]*i|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bchmod\b|\bln\b|\bdd\b|\binstall\b)")
WRITERS = {"tee", "mv", "cp", "rm", "truncate", "chmod", "ln", "dd", "install"}
WRAPPERS = {"sudo", "env", "command", "nohup", "nice", "time", "timeout", "exec", "xargs"}
SHELLS = {"bash", "sh", "zsh", "dash"}
SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", ";;"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1")


def _unquoted_heredoc(line: str) -> bool:
    """Whether a line starts a here-document outside quotes; one that cannot be
    read on its own is taken as not, so its next lines are read as commands."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        # A quoted "<<EOF" stays one word; an operator is a token of its own.
        return "<<" in list(lexer)
    except ValueError:
        return False


def _without_heredocs(command: str) -> str:
    """The command with each here-document's body removed: its lines are data."""
    kept: list[str] = []
    ends: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if ends:
            word, tabs = ends[0]
            if (line.lstrip("\t") if tabs else line) == word:
                ends.pop(0)
            continue
        kept.append(line)
        if HEREDOC.search(line) and _unquoted_heredoc(line):
            ends += [(m.group(2), m.group(0).startswith("<<-")) for m in HEREDOC.finditer(line)]
    return "\n".join(kept)


def shell_writes(command: str, depth: int = 0) -> list[str] | None:
    """The paths a shell command may write: redirection targets, the operands
    of commands that write theirs, and the same inside bash -c or eval. None
    when the command cannot be read, so the caller falls back to WRITES."""
    lexer = shlex.shlex(_without_heredocs(command).replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    targets: list[str] = []
    for segment in segments:
        words: list[str] = []
        index = 0
        while index < len(segment):
            token = segment[index]
            operand = segment[index + 1] if index + 1 < len(segment) else ""
            if set(token) <= set("<>&|") and ">" in token:
                if not (token.endswith("&") and (operand.isdigit() or operand == "-")) and operand != "/dev/null":
                    targets.append(operand)
                index += 2
            elif set(token) <= set("<>&|") and "<" in token:
                index += 2
            else:
                words.append(token)
                index += 1
        while words and (re.fullmatch(r"[A-Za-z_]\w*=.*", words[0]) or words[0] in WRAPPERS):
            words.pop(0)
            while words and (words[0].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", words[0])):
                words.pop(0)
        if not words:
            continue
        name, rest = Path(words[0]).name, words[1:]
        operands = [word for word in rest if not word.startswith("-")]
        flags = rest[: next((i for i, word in enumerate(rest) if not word.startswith("-")), len(rest))]
        script = name in SHELLS and any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", word) for word in flags)
        if script or name == "eval":
            inner = " ".join(rest) if name == "eval" else operands[0] if operands else ""
            found = shell_writes(inner, depth + 1) if depth < 3 else None
            if found is None:
                return None
            targets += found
        elif name == "dd":
            targets += [word[3:] for word in rest if word.startswith("of=")]
        elif (
            name in WRITERS
            or (name in {"sed", "perl"} and any(re.fullmatch(r"-[a-zA-Z]*i\S*|--in-place\S*", word) for word in rest))
            or (name == "find" and ("-delete" in rest or bool(WRITERS & set(rest))))
        ):
            targets += operands
    return targets


def ask(reason: str, decision: str = "ask") -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason
            + " Agents do not change it; if your task needs it, set the task to blocked and say why.",
        }
    }))
    return 0


def relative(target: str, cwd: Path) -> str | None:
    path = Path(target)
    if not path.is_absolute():
        path = cwd / path
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None


def edited(current: str, tool: str, args: dict[str, object]) -> str | None:
    """A file's content after a Write, Edit or MultiEdit, or None if it cannot be told."""
    if tool == "Write":
        content = args.get("content")
        return content if isinstance(content, str) else None
    edits = args.get("edits") if tool == "MultiEdit" else [args]
    text = current
    for edit in edits if isinstance(edits, list) else []:
        if not isinstance(edit, dict):
            return None
        old, new = edit.get("old_string"), edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        text = text.replace(old, new) if edit.get("replace_all") else text.replace(old, new, 1)
    return text


def hook_pre_tool() -> int:
    """PreToolUse hook: ask before a tool writes a protected path or a task's
    Acceptance. Shell commands are read with a heuristic; the gate, the
    commit-msg hook and landing are what hold the rule."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    tool = str(payload.get("tool_name") or "")
    args = payload.get("tool_input") or {}
    if not isinstance(args, dict):
        return 0
    cwd = Path(str(payload.get("cwd") or ROOT))
    # With permission prompts off (a build agent in its sandbox) nobody can
    # answer an ask, and only a deny is documented to hold in that mode.
    decision = "deny" if payload.get("permission_mode") == "bypassPermissions" else "ask"
    answer = partial(ask, decision=decision)
    patterns = protected_patterns("HEAD" if ref_exists("HEAD") else None)
    if tool == "Bash":
        command = str(args.get("command") or "")
        targets = shell_writes(command)
        if targets is None:
            targets = re.findall(r"[\w./@+-]+", command) if WRITES.search(command) else []
        for token in targets:
            rel = relative(token, cwd)
            if rel and rel != "." and (is_protected(rel, patterns) or is_protected(rel + "/", patterns)):
                return answer(f"This command may write {rel}, which is protected (tools/protected.txt).")
        return 0
    target = args.get("file_path") or args.get("notebook_path")
    if not isinstance(target, str):
        return 0
    rel = relative(target, cwd)
    if rel is None:
        return 0
    if is_protected(rel, patterns):
        return answer(f"{rel} is protected (tools/protected.txt).")
    if TASK_FILE.match(rel):
        current = read_text(ROOT / rel)
        if current is not None:
            after = edited(current, tool, args)
            if after is None or acceptance_block(after) != acceptance_block(current):
                return answer(f"This changes the Acceptance of {rel}, which is protected.")
    return 0


PROMPT_LIMIT = 120_000
LOCKFILES = (
    "bun.lock", "bun.lockb", "uv.lock", "Cargo.lock", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "Gemfile.lock", "go.sum",
)
REVIEW_HEADER = (
    "Do the review yourself now and give it as your reply: do not write a plan, do not call the plan tool "
    "and do not hand the work to subagents. Do not run any command; open a file only when the diff below "
    "is not enough. The files in your workspace are an export of the change's head, with no git repository."
)


def capped(text: str, limit: int) -> str:
    data = text.encode()
    if len(data) <= limit:
        return text
    return data[:limit].decode(errors="ignore") + f"\n[{len(data) - limit} more bytes not shown]\n"


def review_prompt(argv: list[str]) -> None:
    """The review prompt for BASE..HEAD within one command-line argument:
    the instructions, the commits, the changed task files and the gate's
    summary, each capped, then the diff if it fits, else its file list."""
    if len(argv) < 2:
        raise Fail("review-prompt needs BASE and HEAD, and optionally the gate summary file")
    start, head = argv[0], argv[1]
    summary = Path(argv[2]) if len(argv) > 2 else None
    parts = [REVIEW_HEADER, (ROOT / "tools" / "review-prompt.md").read_text(encoding="utf-8")]
    parts.append("## Commits\n" + capped(git("log", "--format=%h %s%n%b", f"{start}..{head}"), 20_000))
    tasks_text = ""
    for task in files_listed("diff", "--name-only", start, head, "--", "tasks/[0-9]*.md"):
        tasks_text += f"## {task}\n" + capped(show(head, task) or "(deleted)\n", 8_000)
    if tasks_text:
        parts.append(capped(tasks_text, 30_000))
    if summary is not None and summary.is_file() and not summary.is_symlink():
        parts.append("## Gate\n" + capped(summary.read_text(encoding="utf-8", errors="replace"), 10_000))
    # A lockfile is generated, so it is named with its counts, not shown.
    locks = git("diff", "--numstat", start, head, "--", *(f":(glob)**/{name}" for name in LOCKFILES))
    if locks.strip():
        parts.append("## Lockfiles\nGenerated; their diffs are not shown (added, removed, path):\n" + locks)
    fixed = "\n\n".join(parts)
    diff = git("diff", start, head, "--", ".", *(f":(exclude,glob)**/{name}" for name in LOCKFILES))
    listing = git("diff", "--stat=200", start, head)
    if len((fixed + diff).encode()) + 100 <= PROMPT_LIMIT:
        prompt = fixed + "\n\n## Diff\n" + diff
    else:
        prompt = (
            fixed + f"\n\n## Diff\nThe diff is {len(diff.encode())} bytes, too long to include. "
            "These files changed; read them in your workspace, with read-only commands "
            "(cat, sed -n, grep) if your tools need one, and nothing else:\n" + listing
        )
    if len(prompt.encode()) > PROMPT_LIMIT:
        raise Fail(f"the review prompt is {len(prompt.encode())} bytes even without the diff; review a smaller change")
    sys.stdout.write(prompt)


def export(argv: list[str]) -> None:
    """Write REV's tree into DIR exactly as committed, for a reviewer to read:
    every blob byte for byte (no .gitattributes export rules apply), and a
    symbolic link as a small text file naming its target, so nothing in the
    export points outside it."""
    if len(argv) != 2:
        raise Fail("export needs REV and DIR")
    rev, dest = argv[0], Path(argv[1])
    entries = []
    for entry in git("ls-tree", "-r", "-z", "--full-tree", rev).split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, kind, sha = meta.split()
        parts = Path(path).parts
        if kind != "blob" or Path(path).is_absolute() or ".." in parts:
            continue
        entries.append((mode, sha, path))
    batch = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=ROOT, input="".join(f"{sha}\n" for _, sha, _ in entries).encode(),
        capture_output=True, check=True,
    ).stdout
    offset = 0
    for mode, _, path in entries:
        header_end = batch.index(b"\n", offset)
        size = int(batch[offset:header_end].split()[2])
        data = batch[header_end + 1 : header_end + 1 + size]
        offset = header_end + 1 + size + 1
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            target.write_text(f"(a symbolic link to {data.decode(errors='replace')})\n", encoding="utf-8")
        else:
            target.write_bytes(data)
    print(f"export: {len(entries)} file(s)")


SKIP_DIRS = {"node_modules", "target", ".venv", "vendor", ".gate", ".git"}


def roots(argv: list[str]) -> None:
    """The directories holding a manifest, one per line; with --outermost, only
    those not inside another (a Cargo workspace runs once, at its root)."""
    if not argv:
        raise Fail("roots needs a manifest name")
    manifest = argv[0]
    found = sorted({
        str(Path(rel).parent) for rel in tracked_and_new()
        if Path(rel).name == manifest and not SKIP_DIRS & set(Path(rel).parts)
    })
    if "--outermost" in argv:
        kept: list[str] = []
        for d in found:
            if not any(k == "." or d.startswith(k + "/") for k in kept):
                kept.append(d)
        found = kept
    for d in found:
        print(d)



def landing_cache(argv: list[str]) -> None:
    """Save a successful gate before review; reuse only its exact local inputs."""
    if len(argv) not in {5, 6} or argv[0] not in {"key", "load", "save"}:
        raise Fail("landing-cache needs key|load|save RECORD TIP BASE SUMMARY [EXPECTED_KEY]")
    action, name, tip, base, summary_name = argv[:5]
    record, summary = Path(name), Path(summary_name)
    # These describe the reviewer, the terminal or the one process that runs
    # the check, never what a gate step reads: a systemd unit's invocation and
    # journal stream and an agent's tool call differ on every run, and kept in,
    # no passed gate was ever reused. Every other environment value
    # participates, so an unknown variable costs a rerun, never a stale pass;
    # only the hash is saved.
    ignored = {"PWD", "OLDPWD", "SHLVL", "_", "INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID",
               "MANAGERPID", "MANAGERPIDFDID", "NOTIFY_SOCKET", "WATCHDOG_PID", "WATCHDOG_USEC",
               "LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES", "CODEX_TOOL_CALL_ID"}
    environment = {
        key: value for key, value in os.environ.items()
        if key not in ignored and not key.startswith(("REVIEW_", "FAKE_REVIEW_"))
    }
    tools: dict[str, list[str | int] | None] = {}
    for tool in ("git", "python3", "uv", "node", "npm", "pnpm", "cargo", "go", "shellcheck", "qmllint", "qmltestrunner"):
        found = shutil.which(tool)
        if found is None:
            tools[tool] = None
            continue
        resolved = Path(found).resolve()
        stat = resolved.stat()
        with resolved.open("rb") as binary:
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
        version_text = "binary digest only"
        # qmltestrunner initializes a display even for some informational flags.
        if tool != "qmltestrunner":
            try:
                version = subprocess.run([found, "version" if tool == "go" else "--version"],
                                         capture_output=True, text=True, timeout=3, check=False)
                version_text = f"{version.returncode}:{version.stdout}:{version.stderr}"
            except (OSError, subprocess.TimeoutExpired) as error:
                raise Fail(f"cannot fingerprint {tool}: {type(error).__name__}") from error
        tools[tool] = [str(resolved), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, digest, version_text]
    inputs = {"tip": tip, "base": base, "host": tuple(os.uname()), "python": sys.version,
              "environment": environment, "tools": tools}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()

    def publish(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as output:
            temporary = Path(output.name)
            try:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    if action == "key":
        print(key)
        return
    if action == "save":
        if len(argv) != 6 or argv[5] != key:
            raise Fail("gate environment changed during the check; run the check again")
        text = summary.read_text(encoding="utf-8")
        publish(record, json.dumps({"key": key, "at": time.time(), "summary": text,
                                  "digest": hashlib.sha256(text.encode()).hexdigest()}) + "\n")
        return
    try:
        saved = json.loads(record.read_text(encoding="utf-8"))
        text = saved["summary"]
        age = time.time() - saved["at"]
        valid = (saved["key"] == key and 0 <= age <= 86400 and isinstance(text, str)
                 and bool(text.strip()) and hashlib.sha256(text.encode()).hexdigest() == saved["digest"])
    except (OSError, ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        raise Fail("no matching completed full gate")
    publish(summary, text)


def acp_config(argv: list[str]) -> None:
    """Validate a coordinator descriptor and emit lossless NUL framed fields."""
    if len(argv) != 1:
        raise Fail("acp-config needs a descriptor")
    config = json.loads(Path(argv[0]).read_text())
    required = {"version", "argv", "family", "account", "roles", "metadata", "implementation_version"}
    optional = {"requirements", "runtime_mounts", "context_socket_dir", "context_run_id", "context_runtime_root", "environment_refs", "home"}
    if not isinstance(config, dict) or not required <= config.keys() or config.keys() - required - optional:
        raise Fail("ACP descriptor has invalid fields")
    if type(config["version"]) is not int or config["version"] != 1:
        raise Fail("unsupported ACP descriptor version")
    command = config["argv"]
    if (not isinstance(command, list) or not command or not command[0]
            or any(not isinstance(arg, str) or "\x00" in arg for arg in command)):
        raise Fail("ACP argv must be nonempty strings without NUL (empty arguments are allowed)")
    if not isinstance(config["implementation_version"], str) or not config["implementation_version"] or any(c in config["implementation_version"] for c in "\n\r\x00"):
        raise Fail("invalid ACP implementation_version")
    for field in ("family", "account"):
        value = config[field]
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
            raise Fail(f"invalid ACP {field}")
    if config["roles"] != ["worker"] or not isinstance(config["metadata"], dict):
        raise Fail("ACP descriptor needs worker role and metadata")
    environment_refs = config.get("environment_refs", {})
    if not isinstance(environment_refs, dict):
        raise Fail("ACP environment_refs must map target to source variable names")
    for key, source in environment_refs.items():
        if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source):
            raise Fail("invalid ACP environment source reference")
        if (not isinstance(key, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or key in {
                "HOME", "USER", "LOGNAME", "PATH", "TMPDIR", "TEMP", "TMP", "ENV", "BASH_ENV", "SHELLOPTS",
                "RUSTUP_HOME", "GOPATH", "GOFLAGS"}
                or key.startswith(("GIT_", "PYTHON", "LD_", "XDG_", "ARIVU_", "AGENT_"))):
            raise Fail(f"reserved or invalid ACP environment reference: {key}")
        if source not in os.environ:
            raise Fail(f"missing ACP environment reference: {source}")
    for field in optional - {"context_run_id", "environment_refs"}:
        if field in config:
            value = config[field]
            if (not isinstance(value, str) or not value.startswith("/")
                    or any(char in value for char in "\n\r\x00") or ".." in Path(value).parts):
                raise Fail(f"invalid ACP {field} path")
            if not Path(value).exists():
                raise Fail(f"missing ACP {field}")
    if "context_socket_dir" in config:
        if not isinstance(config.get("context_run_id"), str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", config["context_run_id"]):
            raise Fail("ACP context needs context_run_id")
        directory = Path(config["context_socket_dir"])
        if (not directory.is_dir() or directory.is_symlink() or directory.stat().st_mode & 0o077
                or directory.stat().st_uid != os.getuid() or any(directory.iterdir())
                or len(os.fsencode(directory / "context.sock")) > 107):
            raise Fail("ACP context socket directory must be private")
    if "home" in config:
        # An account's login home, shared by its workers: private to GG's user,
        # and never his own home or a directory holding it.
        if not isinstance(config["home"], str) or not os.path.isabs(config["home"]):
            raise Fail("ACP home must be an absolute path")
        home = Path(config["home"])
        real_home = Path(os.environ["HOME"]).resolve()
        if (not home.is_dir() or home.is_symlink() or home.stat().st_uid != os.getuid()
                or home.stat().st_mode & 0o022 or real_home.is_relative_to(home.resolve())):
            raise Fail("ACP home must be a private directory of its own, not the user's home")
    if "context_runtime_root" in config and "runtime_mounts" not in config:
        raise Fail("ACP context runtime root needs read-only runtime mounts")
    if "runtime_mounts" in config:
        mounts = json.loads(Path(config["runtime_mounts"]).read_text())
        lock_directory = Path(f"/run/user/{os.getuid()}/arivu/locks")
        if not isinstance(mounts, list) or any(
                not isinstance(m, dict) or (m.get("access") != "read" and not (
                    m.get("access") == "write" and Path(m.get("path", "")).resolve() == lock_directory)) for m in mounts):
            raise Fail("ACP runtime mounts must be read-only except the shared lock directory")
        if "context_runtime_root" in config and not any(
                mount["access"] == "read" and Path(config["context_runtime_root"]).resolve().is_relative_to(
                    Path(mount["path"]).resolve()) for mount in mounts):
            raise Fail("ACP context runtime root needs an explicit read-only mount")
        # Validate every mount before any shell output or worktree creation.
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            runtime_mounts([config["runtime_mounts"]])
    values = ["ACP-CONFIG-1", config.get("requirements", ""), config.get("runtime_mounts", ""),
              config.get("context_socket_dir", ""), config.get("context_run_id", ""),
              config.get("context_runtime_root", ""), config.get("home", ""), str(len(environment_refs)),
              *[value for key, source in environment_refs.items() for value in (key, os.environ[source])], *command]
    sys.stdout.buffer.write("\x00".join([*values, "ACP-CONFIG-OK", ""]).encode())


def worker_saves(argv: list[str]) -> None:
    """Promote bounded data refs after strict import, never worker configuration."""
    if len(argv) != 3 or not re.fullmatch(r"[a-z0-9-]+", argv[2]):
        raise Fail("worker-saves needs CANONICAL_REPO PRIVATE_REFS NAME")
    repo, private, name = Path(argv[0]), Path(argv[1]), argv[2]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root = os.open(private, flags)
        try:
            saved = os.open("saved", flags, dir_fd=root)
        finally:
            os.close(root)
    except OSError as error:
        raise Fail("worker savepoint directory is unavailable or not a real directory") from error
    try:
        with os.scandir(saved) as entries:
            for count, entry in enumerate(entries):
                if count >= 4096:
                    raise Fail("worker savepoint reference count exceeds limit")
                if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9]{6}", entry.name):
                    continue
                try:
                    descriptor = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=saved)
                except OSError as error:
                    raise Fail("worker savepoint reference is not a regular data file") from error
                try:
                    info = os.fstat(descriptor)
                    if not stat.S_ISREG(info.st_mode) or info.st_size not in {40, 41, 64, 65}:
                        raise Fail("worker savepoint reference is not bounded object data")
                    data = os.read(descriptor, 66)
                finally:
                    os.close(descriptor)
                if not re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\n?", data):
                    raise Fail("worker savepoint reference has invalid object data")
                oid = data.decode().strip()
                command = ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
                kind = subprocess.run([*command, "cat-file", "-t", oid], capture_output=True, text=True, check=False, env=environment)
                if kind.returncode or kind.stdout.strip() != "commit":
                    raise Fail("worker savepoint commit has not been strictly imported")
                result = subprocess.run([*command, "update-ref", "--no-deref", f"refs/arivu/worker-saved/{name}/{entry.name}", oid],
                                        capture_output=True, text=True, check=False, env=environment)
                if result.returncode:
                    raise Fail("worker savepoint promotion failed")
    finally:
        os.close(saved)


def acp_authors(argv: list[str]) -> None:
    """Only coordinator records matching each ACP session establish a family."""
    log, agent, branch = Path(argv[0]), argv[1], argv[2]
    if not log.exists():
        return
    sessions = []
    for line in log.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "acp":
            if len(fields) != 3:
                raise Fail("malformed ACP session provenance")
            sessions.append(fields)
    if not sessions:
        return
    try:
        records = [json.loads(line) for line in log.with_name("sessions.jsonl").read_text().splitlines()]
    except (OSError, ValueError) as error:
        raise Fail("ACP session has no coordinator provenance") from error
    families = set()
    for stamp, _, tip in sessions:
        matches = [record for record in records if isinstance(record, dict) and record.get("at") == stamp
                   and record.get("tip") == tip and record.get("agent") == agent and record.get("branch") == branch]
        if len(matches) != 1 or matches[0].get("family") not in {"openai", "google", "anthropic"}:
            raise Fail("ACP author family needs matching coordinator classification")
        families.add(matches[0]["family"])
    print(",".join(sorted(families)))


def acp_provenance(argv: list[str]) -> None:
    """Record supplied implementation metadata separately from trusted family checks."""
    config = json.loads(Path(argv[0]).read_text())
    record = {key: config[key] for key in ("family", "account", "implementation_version", "roles", "metadata")}
    record.update(at=argv[4], tip=argv[5], agent=argv[2], branch=argv[3])
    with Path(argv[1]).open("a") as output:
        output.write(json.dumps(record) + "\n")


def managed_home(argv: list[str]) -> None:
    """Prepare explicit managed filesystem mountpoints without copying contents."""
    if len(argv) != 2:
        raise Fail("managed-home needs PRIVATE_HOME REQUIREMENTS")
    _managed_home(argv, defaults=False)


def codex_home(argv: list[str]) -> None:
    _managed_home(argv, defaults=True)


def _managed_home(argv: list[str], *, defaults: bool) -> None:
    """Prepare managed mount targets without importing host settings or secrets."""
    if len(argv) not in {1, 2}:
        raise Fail("codex-home needs PRIVATE_HOME [REQUIREMENTS]")
    private = Path(argv[0])
    requirements = Path(argv[1] if len(argv) == 2 else "/etc/codex/requirements.toml")
    if private.is_symlink():
        raise Fail("private home is a symbolic link")
    private.mkdir(parents=True, exist_ok=True)
    config = tomllib.loads(requirements.read_text()) if requirements.exists() else {}
    profiles = config.get("permissions", {})
    paths = [Path.home() / ".claude", Path.home() / ".codex/config.toml"] if defaults else []
    directories = {Path.home() / ".claude"} if defaults else set()
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        for name, access in profile.get("filesystem", {}).items():
            if access == "read" and name.startswith("/"):
                path = Path(name)
                paths.append(path)
                if path.is_dir():
                    directories.add(path)
    for source in paths:
        try:
            relative = source.relative_to(Path.home())
        except ValueError:
            continue
        if not relative.parts or ".." in relative.parts:
            continue
        parts = relative.parts if source in directories else relative.parts[:-1]
        target = private
        for part in parts:
            target /= part
            if target.is_symlink():
                raise Fail(f"managed mount parent is a symbolic link: {target}")
            target.mkdir(exist_ok=True)
        if source not in directories and (source.is_file() or source.name == "config.toml"):
            target = private / relative
            # Do not follow a link supplied by an earlier worker session.
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                if not stat.S_ISREG(target.lstat().st_mode):
                    raise Fail(f"managed mount target is not a regular file: {target}") from None
            else:
                with os.fdopen(descriptor, "w") as output:
                    if target.suffix == ".json":
                        output.write("{}\n")


def runtime_mounts(argv: list[str]) -> None:
    """Read coordinator-provided same-path mounts, never shell expressions."""
    if len(argv) not in {1, 2}:
        raise Fail("runtime-mounts needs a manifest [PRIVATE_HOME]")
    mounts = json.loads(Path(argv[0]).read_text())
    if not isinstance(mounts, list):
        raise Fail("runtime mounts must be a list")
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != {"path", "access"}:
            raise Fail("runtime mount needs path and access")
        path, access = mount["path"], mount["access"]
        if not isinstance(path, str) or not path.startswith("/") or any(c in path for c in "\n\r\x00"):
            raise Fail("runtime mount needs an absolute single-line path")
        if Path(path).resolve() in {Path("/"), Path.home().resolve(), Path.home().parent.resolve()} or ".." in Path(path).parts:
            raise Fail("runtime mounts cannot expose the whole home or filesystem")
        if access not in {"read", "write"} or not Path(path).exists():
            raise Fail(f"runtime mount is missing or has invalid access: {path}")
        if len(argv) == 2 and Path(path).is_relative_to(Path.home()):
            target = Path(argv[1])
            for part in Path(path).relative_to(Path.home()).parts:
                target /= part
                if target.is_symlink():
                    raise Fail(f"runtime mount destination is a symbolic link: {target}")
        print("--ro-bind" if access == "read" else "--bind")
        print(Path(path).resolve(strict=True))
        print(path)


CHECKS = {
    "commit-msg": check_commit_msg,
    "hooks": lambda argv: check_hooks(),
    "conflicts": lambda argv: check_conflicts(),
    "prose": lambda argv: check_prose(),
    "protected": lambda argv: check_protected(),
    "tests-removed": lambda argv: check_tests_removed(),
    "symlinks": lambda argv: check_symlinks(),
    "secrets": check_secrets,
    "agents-md": lambda argv: check_agents_md(),
    "spec": lambda argv: check_spec(),
    "tasks": check_tasks,
    "manifest": lambda argv: check_manifest(),
    "declarations": check_declarations,
    "roots": roots,
    "review-prompt": review_prompt,
    "export": export,
    "landing-cache": landing_cache,
    "acp-config": acp_config,
    "acp-provenance": acp_provenance,
    "acp-authors": acp_authors,
    "worker-saves": worker_saves,
    "managed-home": managed_home,
    "codex-home": codex_home,
    "runtime-mounts": runtime_mounts,
}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: tools/checks.py <" + "|".join([*CHECKS, "stream-text", "hook-stop", "hook-pre-tool"]) + "> [args]")
        return 2
    name, rest = argv[0], argv[1:]
    if name == "stream-text":
        print(stream_text(sys.stdin.read()))
        return 0
    if name == "hook-stop":
        return hook_stop()
    if name == "hook-pre-tool":
        return hook_pre_tool()
    if name not in CHECKS:
        print(f"ERROR unknown check {name}")
        return 2
    try:
        CHECKS[name](rest)
    except Fail as e:
        print(f"ERROR {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
