# 0001: Keep backticks inside a line

Status: merged
Why: review of task 0001 found that removing "a surrounding pair of backticks" turned `` `echo a` && `echo b` `` into ``echo a` && `echo b``. The pair is removed only when the line holds no other backtick.

## Modified

### REQ-CLEAN-01: One command line from an answer
When `sol --clean` reads an answer, the system shall: drop carriage returns; when the answer holds a fenced block, keep only the first block's lines; trim each line; drop blank lines and lines starting with `#`; remove a leading `$ `, and a pair of backticks around a line that holds no other backtick; then join the lines, with a space after a line ending in `\` (the backslash removed), `|`, `&&` or `||`, and with ` && ` otherwise.
Acceptance: every `spec/cases/clean/NN-name.in` cleans to its `.out` (`tests/acceptance/sol.sh`, REQ-CLEAN-01).

## Tests

- Added `spec/cases/clean/13-inner-backticks-kept`.
