# 0005: Feedback while sol waits

Status: review
Depends on: 0004
Spec: REQ-WIDGET-06
Goal: Ctrl+G shows that sol is working, with the time so far, and leaves a clean line or the reason (change 0004).

Acceptance:
- run: `shellcheck sol tests/acceptance/sol.sh tools/ci-setup.local.sh`
- run: `tests/acceptance/sol.sh`
- run: `python3 -I tests/acceptance/widget.py`
- run: `uv run -q --no-project --with pyte==0.8.2 python tests/acceptance/screen.py`

## Log

- 2026-11-20: created at GG's word.
- 2026-11-20: built. The screen test fails its spinner checks on the old sol and passes on the new one, in bash and zsh; the failure checks pass on both, guarding the behavior the spinner shares a line with.
