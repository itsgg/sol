# 0001: Ctrl+G turns the bash line into a command

Status: done
Depends on: none
Spec: REQ-CMD-01, REQ-CMD-02, REQ-CMD-03, REQ-CMD-04, REQ-CLEAN-01, REQ-CTX-01, REQ-CTX-02, REQ-WIDGET-01, REQ-WIDGET-02, REQ-WIDGET-03, REQ-WIDGET-04, REQ-PERF-01
Goal: the whole first release of SEED section 9 in one slice, since each part alone is not usable: the `sol` command over `vazhi ask --fast`, the cleaning and context rules, and the Ctrl+G widget, tested with a stub vazhi in a real interactive bash.

Acceptance:
- run: `shellcheck sol tests/acceptance/sol.sh`
- run: `tests/acceptance/sol.sh`
- run: `python3 -I tests/acceptance/widget.py`
- GG presses Ctrl+G on a request in his own foot terminal and gets the command on the line.

## Log

- 2026-11-20: created.
- 2026-11-20: built. sol, its cleaning and context rules, and the widget; 23 command checks and 5 widget checks pass with a stub vazhi. Measured: sol's own time 24 ms median; end to end through vazhi's fast list 0.5 to 0.7 s on three live requests. Found and fixed while testing: inside bind -x, `fc -ln -5` leaves out the latest command, so the widget sends `history 5` instead.
- 2026-11-20: landed; GG has used Ctrl+G at his prompt (the acceptance line read by eye); done.
