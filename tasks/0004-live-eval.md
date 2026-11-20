# 0004: A scored live eval

Status: review
Depends on: 0003
Spec: none
Goal: a prompt or fast-list change is measured, not judged by eye: tests/live/eval.py runs spec/cases/live.tsv through the real vazhi and prints a score. No requirement changes; the eval is never gated.

Acceptance:
- run: `python3 -I -c "import ast,sys; ast.parse(open('tests/live/eval.py').read())"`
- run: `test "$(./sol --version)" = 0.2.0`
- GG or the coordinator runs `tests/live/eval.py` and records the score here.

## Log

- 2026-11-20: created.
- 2026-11-20: built. Score 33/33 (eleven requests, three runs, slowest 1.4 s). Against a stub that always answers `ls -la` the same eval scores 0/11, so the patterns reject a wrong command.
