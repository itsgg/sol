# 0003: zsh widget, and old bash refused

Status: review
Depends on: 0002
Spec: REQ-WIDGET-05, REQ-CMD-06, REQ-CMD-02
Goal: Sol works for zsh users, and on a bash too old to run it says so plainly (change 0003, SEED D5).

Acceptance:
- run: `shellcheck sol tests/acceptance/sol.sh tools/ci-setup.local.sh`
- run: `tests/acceptance/sol.sh`
- run: `python3 -I tests/acceptance/widget.py`

## Log

- 2026-11-20: created at GG's word.
- 2026-11-20: built. zsh 5.9.2 installed here for the tests; every widget case passes in bash and zsh on a pty, including aliases (zsh prints them as name=value) and the latest command in history.
