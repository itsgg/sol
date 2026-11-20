# Working on Sol

Plain words to a shell command on Ctrl+G, through vazhi's free models. Read SEED.md (purpose, principles and decisions) and SPEC.md (the contract you build against) before changing anything. They take precedence in that order over a task, and a task over the code. If a task conflicts with either, stop and write the conflict in the task's Log; never resolve it by editing SEED.md or SPEC.md.

## Commands

- `tools/gate --turn`: the fast gate; the pre-commit hook and the end of every Claude Code turn run it.
- `tools/gate`: the full gate every merge passes.
- `tools/gate --nightly`: the full gate plus the slow steps.
- `tools/agent-loop NAME HARNESS [SESSIONS]`: run a build agent in its own sandboxed worktree.
- `tools/land check BRANCH`: the coordinator's full gate and review before a merge.

## Taking work

1. Tasks live in `tasks/NNNN-name.md`, in the format of `tasks/README.md`. Take the task your prompt names, when the coordinator names one (`tools/agent-loop` fails a session whose branch changes another task's file); otherwise take the lowest-numbered task whose Status is open and whose Depends on are all done.
2. Claim it by creating `task-locks/NNNN.lock` in the repository's shared git directory (`$(git rev-parse --git-common-dir)/task-locks/`, which every worktree and worker sees) with your agent name and the UTC time. Never commit a lock: the gate's tasks step refuses one under `tasks/locks/`. A lock younger than four hours belongs to someone else; take another task.
3. Work in your own worktree on the branch `agent/<your name>`. Never commit to main, never merge and never push: the coordinator lands work with `tools/land`.
4. Write or confirm the task's acceptance test first. It fails before your change and passes after it.
5. Done means every `run:` command under the task's Acceptance passes and `tools/gate` passes. Then set Status to review, add a dated Log entry saying what changed and what you measured, commit, and delete your lock.
6. One task per session. If you are stuck, or the task needs a protected change you cannot justify, set Status to blocked, write why in the Log, commit, delete your lock and stop. Blocked is a good outcome.

## Rules, and what holds each one

1. Never edit SEED.md or SPEC.md. Propose a change to the spec in `changes/NNNN-name.md`, in the format of `changes/README.md`; the coordinator merges it. Held by `tools/protected.txt`.
2. Never weaken a check, test, tolerance, gate step or task acceptance to make work pass. A commit that changes a protected path says so on a `Protected: <path>: <why>` line, one that removes a test on a `Removes test: <name>: <why>` line, and one that edits an existing test on a `Modifies test: <name>: <why>` line, so review sees it. Held by the commit-msg hook, the gate's protected and tests-removed steps, and `tools/land merge`, which needs the coordinator's acceptance.
3. Every behavior lands with tests. A test that checks a SPEC requirement names its ID (REQ-AREA-NN) in its name or a comment. Held by the gate's spec step, for tasks in review or done.
4. Plain ASCII in prose, commits and comments: no em dashes, curly quotes or arrows, and no spaced hyphen standing in for a dash. Held by the gate's prose step and the commit-msg hook; comments by review.
5. Commit subjects follow Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`), with no full stop; the body says what changed and why. Never add a trailer or a line crediting the change or its review to a model, a vendor, a tool, an agent or a reviewer. Held by the commit-msg hook.
6. Keep command output short and put detail in log files. An error line starts with ERROR and says what to do. Held by review.
7. Data and caches live under `~/.local/share/sol`, never in /tmp or the repository. Tests make no network calls. Held by review.

## Landing, for the coordinator

`tools/land check BRANCH` runs the full gate (in the agent's sandbox for `agent/*`) and one review by a model family other than the author's. A retry reuses a matching saved review and a full gate completed within 24 hours for the same commit, base and local environment; `--fresh-gate` forces another gate. Verify each finding yourself and fix the real ones with a test on the branch; check again with `--no-review`. `tools/land merge BRANCH` fast-forwards main, and `tools/land push` pushes it, as separate commands. Accept a declared protected change with `--accept-protected` only when it adds or tightens a check; a change that loosens or removes one waits for GG. A declared test edit or removal is accepted when SPEC.md, a merged change in `changes/` or the task says the behavior it checks changed; one that checks the same behavior more loosely waits for GG. Findings and verdicts go to GG in the conversation, never into the repository.

## Project

- `tests/acceptance/sol.sh`, `python3 -I tests/acceptance/widget.py` and `uv run --no-project --with pyte==0.8.2 python tests/acceptance/screen.py`: the tests of record, with a stub vazhi and no network; `shellcheck sol tests/acceptance/sol.sh` lints. The tasks' acceptance runs them, so the full gate does.
- `./sol --dry-run REQUEST` shows the prompt without calling vazhi. `tests/live/eval.py` scores live answers through the real vazhi (network, keys, about a minute); run it before changing the prompt, never in the gate.
- `sol` never runs the command it makes, and never calls a model provider itself: models are vazhi's (SEED P1, P4).
