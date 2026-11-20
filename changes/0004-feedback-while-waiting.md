# 0004: Feedback while sol waits

Status: merged
Why: GG, 2026-11-20: "can you add some feedback ... while sol is prepare the command". Ctrl+G showed nothing for the 0.5 to 3.5 s a model takes, so it looked as if nothing happened.

## Added

### REQ-WIDGET-06: Feedback while sol waits
While a widget waits for `sol`, the system shall show `<frame> sol: thinking <s>.<tenths>s` on the line, dim, with a frame from `|/-\` and the elapsed time updated every 0.1 s, and shall clear it before the line is redrawn; on failure the reason stays on screen (above the prompt in bash, below it in zsh) and the request stays on the line. `sol` draws it only when SOL_FEEDBACK is 1 and /dev/tty opens, so scripts calling `sol` see nothing.
Acceptance: `tests/acceptance/screen.py` (REQ-WIDGET-06) in bash and zsh on a pty behind a 60x10 pyte terminal, with a stub vazhi that answers after a second: the spinner shows while waiting, the screen afterwards holds only the command, and on failure the reason and the request.

## Tests

- Added `tests/acceptance/screen.py`; CI installs uv for it.
