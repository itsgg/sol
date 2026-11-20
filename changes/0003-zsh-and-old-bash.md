# 0003: A zsh widget, and old bash refused plainly

Status: merged
Why: GG, 2026-11-20, asked whether Sol is specific to his machine and then to fix what was: it worked only in bash, and on macOS's bash 3.2 it would fail with an obscure error. SEED D5.

## Added

### REQ-WIDGET-05: The zsh widget
While zsh's line editor is active, when Ctrl+G is pressed on a non-blank line, the widget that `sol --init zsh` prints shall call `sol` with the line, `alias` output, `fc -ln -5` output, `$PWD` and the zsh version, and on exit 0 set BUFFER to the command and CURSOR to its end, running nothing; on failure it shall leave BUFFER as it was and redraw the prompt. REQ-WIDGET-03 and REQ-WIDGET-04 hold for it as for bash.
Acceptance: `tests/acceptance/widget.py` (REQ-WIDGET-05) runs the widget cases in an interactive zsh on a pty as well as in bash.

### REQ-CMD-06: Old bash refused
If `sol` runs under bash older than 4, then it shall print `sol: needs bash 4 or later to run; this is bash <N> (on macOS: brew install bash)` to stderr and exit 2.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-06), with SOL_TEST_BASH_MAJOR standing in for the version.

## Modified

### REQ-CMD-02: Bad usage
If `sol` gets no request, a blank request, or `--init` with anything but `bash` or `zsh`, then it shall print usage to stderr and exit 2.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-02).

## Tests

- `tests/acceptance/widget.py` runs every widget case in bash and zsh; `tests/acceptance/sol.sh` checks `--init fish` instead of `--init zsh` as bad usage, and adds REQ-CMD-06.
- SOL_ALIASES accepts zsh's `name=value` lines as well as bash's `alias name='value'`.
