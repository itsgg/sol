# 0002: Aliased commands run as the original, and directory names in the context

Status: merged
Why: GG, 2026-11-20: "list the oldest files" gave `ls -lt | tail -1`, which failed because ls is aliased to eza, whose -t takes a field; "list bak files" gave `ls *.bak` where the files were below the current directory; a request about downloads gave `~/downloads` for `~/Downloads`. Telling the model about aliases did not hold: the same prompt gave `command ls` on one run and bare `ls -lt` on the next (2026-11-20, Groq Qwen3.8 27B and GPT-OSS 120B). Models write the original program's flags, so sol now rewrites the command instead.

## Added

### REQ-CMD-05: Aliased commands run as the original
When the command has a command word, at its start or after `|`, `;`, `&`, `(` or a backtick, that names an alias in SOL_ALIASES which replaces a command on PATH, the system shall print that word as `command <name>`; it shall send no alias value to vazhi.
Acceptance: every line of `spec/cases/unalias/cases.tsv` (answer, then expected command, tab-separated) with aliases ls (replacing a command) and g (not), and the prompt holds no alias value (`tests/acceptance/sol.sh`, REQ-CMD-05).

### REQ-CTX-03: Directory names
When the current directory holds directories that are not hidden, the system shall add `Directories here: <names>` (up to 40, space-separated) to the context block, after the current directory.
Acceptance: `tests/acceptance/sol.sh` (REQ-CTX-03).

## Modified

### REQ-WIDGET-02: Ctrl+G replaces the line
While bash is reading a line, when Ctrl+G is pressed on a non-blank line, the widget shall call `sol` with the line, `alias` output, `history 5` output (HISTTIMEFORMAT empty), `$PWD` and the bash version, and on exit 0 set READLINE_LINE to the command and READLINE_POINT to its end, running nothing.
Acceptance: `tests/acceptance/widget.py` (REQ-WIDGET-02) in an interactive bash on a pty: the line becomes the command, typing continues at its end, the latest command before it reaches `sol`, and an alias defined in the shell makes `ls` come back as `command ls`.

## Tests

- Added `spec/cases/unalias/cases.tsv`, the REQ-CMD-05 and REQ-CTX-03 checks in `tests/acceptance/sol.sh`, and the alias case in `tests/acceptance/widget.py`.
- The system prompt also asks for find when a request names files without a place; that is prompt text, not a requirement.
