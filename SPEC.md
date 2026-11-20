# Sol: Specification

Created: 2026-11-20. Owner: GG. Derives from SEED.md at commit 8907778, sections 4, 5, 9, 10 and 12. The spec's version is the git commit of this file.

Precedence: SEED.md, then this spec, then plans and tasks, then the code. A conflict with SEED.md goes to GG. Agents never edit this file: they propose deltas in `changes/` (format in `changes/README.md`), and the coordinator merges them.

## 1. Conventions

This spec fixes the interfaces between the widget, the `sol` command and vazhi, the cleaning and context rules, and the failure behavior. SHALL and MUST bind; MAY is optional; "provisional" marks a choice made without measurement. Requirement IDs are REQ-<AREA>-<NN> with areas CMD (the command), CLEAN (answer cleaning), CTX (context), WIDGET (the bash widget) and PERF. Acceptance is by conformance cases in `spec/cases/`, scenarios in `tests/acceptance/sol.sh` and `tests/acceptance/widget.py`, and one measured threshold.

## 2. Scope and non-goals

Covered: the first release of SEED section 9: bash only, one command per request, context of system, shell, directory and the last five commands.

Out: zsh and fish widgets, multi-line scripts, explanations, a confirmation step, offline answers, and any direct call to a model provider (SEED P4). No code may run the command it produces (SEED P1).

## 3. Terms

- Request: the text on the bash line when Ctrl+G is pressed, or the arguments to `sol`.
- Answer: what `vazhi ask` printed.
- Command: the single line `sol` makes of the answer and prints.
- Context: the system prompt's description of the system, shell, directory and recent commands.

## 4. Architecture

Two parts, in one bash script, `sol`:

- The command `sol`: builds the context, calls `vazhi ask --fast`, cleans the answer, prints the command.
- The widget: bash code that `sol --init bash` prints and `~/.bashrc` evaluates. It reads the line and history, calls `sol` by the absolute path it was printed from, and writes the line back.

Dependencies: bash 5 (READLINE_LINE and READLINE_POINT for `bind -x`, SEED R6), coreutils' `readlink`, and `vazhi` 0.2 or later (`vazhi ask --fast --system TEXT -- PROMPT`, SEED R3). Tests also need python 3 for the pty test and shellcheck. Nothing else.

## 5. Data model and invariants

- SOL_HISTORY: the output of `history N` (each command starts with its number and an optional `*`; a multi-line command's later lines carry no number), or plain lines, one command each, when its first non-blank line has no number.
- The system prompt: fixed instructions, then a context block, exactly:

```
System: <PRETTY_NAME from os-release>[ (based on <ID_LIKE>)]
Shell: <SOL_SHELL, or "bash" and the running version>
Current directory: <SOL_CWD, or $PWD>
Directories here: <names>
Recent commands, oldest first:
  <command>
```

The directories line appears only when there are directories (REQ-CTX-03); the last two parts only when a command survives the secret filter. Without os-release, the system is `uname -s`.

- Invariant: `sol` prints at most one line on stdout, and only on exit status 0.

## 6. Behavior

### 6.1 The command

### REQ-CMD-01: Ask vazhi and print the command
When `sol [--] REQUEST...` runs, the system shall call `$SOL_VAZHI` (default `vazhi`) as `ask --fast --system <prompt> -- <request>`, clean its answer by section 6.2, print the command and exit 0.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-01): a request starting with `--` reaches the stub after `--`, and a fenced answer prints as `ls -lS`.

### REQ-CMD-05: Aliased commands run as the original
When the command has a command word, at its start or after `|`, `;`, `&`, `(` or a backtick, that names an alias in SOL_ALIASES which replaces a command on PATH, the system shall print that word as `command <name>`; it shall send no alias value to vazhi.
Acceptance: every line of `spec/cases/unalias/cases.tsv` (answer, then expected command, tab-separated) with aliases ls (replacing a command) and g (not), and the prompt holds no alias value (`tests/acceptance/sol.sh`, REQ-CMD-05).

### REQ-CMD-02: Bad usage
If `sol` gets no request, a blank request, or `--init` with anything but `bash`, then it shall print usage to stderr and exit 2.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-02).

### REQ-CMD-03: No answer
If vazhi exits non-zero, then `sol` shall exit 1 with nothing on stdout, leaving vazhi's own stderr; if vazhi is not found, it shall also print `sol: vazhi not found; install it or set SOL_VAZHI`.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-03).

### REQ-CMD-04: An answer with no command
If cleaning leaves nothing, then `sol` shall print `sol: the answer held no command` to stderr and exit 3 with nothing on stdout.
Acceptance: `tests/acceptance/sol.sh` (REQ-CMD-04).

### 6.2 Cleaning

### REQ-CLEAN-01: One command line from an answer
When `sol --clean` reads an answer, the system shall: drop carriage returns; when the answer holds a fenced block, keep only the first block's lines; trim each line; drop blank lines and lines starting with `#`; remove a leading `$ `, and a pair of backticks around a line that holds no other backtick; then join the lines, with a space after a line ending in `\` (the backslash removed), `|`, `&&` or `||`, and with ` && ` otherwise.
Acceptance: every `spec/cases/clean/NN-name.in` cleans to its `.out` (`tests/acceptance/sol.sh`, REQ-CLEAN-01).

### 6.3 Context

### REQ-CTX-01: The context block
When `sol` builds its prompt, the system shall write the context block of section 5 with at most the last five commands from SOL_HISTORY, numbers stripped and a multi-line command joined with spaces.
Acceptance: `tests/acceptance/sol.sh` (REQ-CTX-01), through `sol --dry-run`, which prints the prompt and the request and calls nothing.

### REQ-CTX-03: Directory names
When the current directory holds directories that are not hidden, the system shall add `Directories here: <names>` (up to 40, space-separated) to the context block, after the current directory.
Acceptance: `tests/acceptance/sol.sh` (REQ-CTX-03).

### REQ-CTX-02: No secrets in the context
If a command in SOL_HISTORY contains, in any case, `key`, `token`, `secret`, `passw`, `passphrase`, `credential`, `bearer`, `authorization`, `auth=`, `cookie` or `private`, or a run of 24 or more characters from `A-Za-z0-9_+=-` holding both a letter and a digit, then the system shall leave that command out of the prompt.
Acceptance: no line of `spec/cases/secret/drop.txt` and every line of `keep.txt` reaches vazhi as sent (`tests/acceptance/sol.sh`, REQ-CTX-02).

### 6.4 The widget

### REQ-WIDGET-01: Printing the widget
When `sol --init bash` runs, the system shall print bash code that parses and binds Ctrl+G with `bind -x '"\C-g": __sol_widget'`.
Acceptance: `tests/acceptance/sol.sh` (REQ-WIDGET-01).

### REQ-WIDGET-02: Ctrl+G replaces the line
While bash is reading a line, when Ctrl+G is pressed on a non-blank line, the widget shall call `sol` with the line, `alias` output, `history 5` output (HISTTIMEFORMAT empty), `$PWD` and the bash version, and on exit 0 set READLINE_LINE to the command and READLINE_POINT to its end, running nothing.
Acceptance: `tests/acceptance/widget.py` (REQ-WIDGET-02) in an interactive bash on a pty: the line becomes the command, typing continues at its end, and the latest command before it reaches `sol`, and an alias defined in the shell makes `ls` come back as `command ls`.

### REQ-WIDGET-03: Failure keeps the line
If `sol` exits non-zero or prints nothing, then the widget shall leave READLINE_LINE and READLINE_POINT as they were.
Acceptance: `tests/acceptance/widget.py` (REQ-WIDGET-03).

### REQ-WIDGET-04: A blank line
If Ctrl+G is pressed on a blank line, then the widget shall return without calling `sol`.
Acceptance: `tests/acceptance/widget.py` (REQ-WIDGET-04).

## 7. Interfaces

```
sol [--] REQUEST...        print one command
sol --dry-run REQUEST...   print the prompt and request, call nothing
sol --clean                clean stdin to one command
sol --init bash            print the widget
sol --help | --version
```

Environment: SOL_HISTORY, SOL_CWD, SOL_SHELL (section 5), SOL_ALIASES (`alias` output; only names are used), SOL_VAZHI (the vazhi command), SOL_OS_RELEASE (the os-release file; for tests).

Exit status: 0 printed a command; 1 no answer; 2 bad usage; 3 the answer held no command. Stdout carries only the command; every message goes to stderr, one line, starting `sol:`.

## 8. Unwanted behavior

Covered by REQ-CMD-02, REQ-CMD-03, REQ-CMD-04 and REQ-WIDGET-03. Ctrl+C while waiting reaches `sol` and vazhi as SIGINT; vazhi aborts and exits non-zero, so REQ-WIDGET-03 applies.

## 9. Quality attributes

### REQ-PERF-01: Sol adds little to vazhi's time
When vazhi answers at once, `sol -- REQUEST` with five history lines shall take under 100 ms, median of 11 runs.
Acceptance: `tests/acceptance/sol.sh` (REQ-PERF-01). Measured 24 ms on GG's laptop, 2026-11-20. Provisional for slower machines.

End-to-end time depends on vazhi's fast list: 0.5 to 0.7 s measured 2026-11-20 (SEED R2). It is checked by eye with `spec/cases/requests.txt`, not gated, since free models change nightly.

## 10. Verification and the gate

Tests of record are `tests/acceptance/sol.sh` (the command, cleaning, context, performance) and `tests/acceptance/widget.py` (the widget in a real bash on a pty). Both use a stub vazhi and make no network calls. Conformance data lives in `spec/cases/clean/` and `spec/cases/secret/`. Task acceptance runs them with shellcheck; the full gate re-runs every task in review or done. The live check is `spec/cases/requests.txt` through the real vazhi, read by GG.

## 11. Protected checks

Beyond `tools/protected.txt` (which covers `tests/acceptance/**` and `spec/cases/**`): the 100 ms threshold in REQ-PERF-01.

## 12. Open questions

- O1 (SEED): zsh and fish. Default: bash only. Owner GG. Next action: none until another shell is in use.

## 13. Changes and retired requirements

- 2026-11-20: created.
- 2026-11-20: change 0001 merged: REQ-CLEAN-01 keeps backticks inside a line.
- 2026-11-20: change 0002 merged: REQ-CMD-05 and REQ-CTX-03 added, REQ-WIDGET-02 sends aliases.

### Retired

None.
