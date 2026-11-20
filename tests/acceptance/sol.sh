#!/usr/bin/env bash
# Tests of record for the sol command (SPEC.md section 6). No network: vazhi is a stub that
# records what it was asked. Usage: tests/acceptance/sol.sh
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
sol=$root/sol
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

fail() {
    echo "FAIL $*"
    failures=$((failures + 1))
}
pass() { echo "ok   $*"; }

# A stub vazhi: records its arguments one per line in $work/args, prints $STUB_ANSWER and
# exits $STUB_STATUS.
cat >"$work/vazhi" <<'EOF'
#!/usr/bin/env bash
: >"$STUB_DIR/args"
for a in "$@"; do printf '%s\0' "$a" >>"$STUB_DIR/args"; done
[ -n "${STUB_STDERR:-}" ] && echo "$STUB_STDERR" >&2
printf '%s' "${STUB_ANSWER:-}"
exit "${STUB_STATUS:-0}"
EOF
chmod +x "$work/vazhi"
export SOL_VAZHI=$work/vazhi STUB_DIR=$work

# The recorded arguments, as an array.
stub_args() {
    args=()
    while IFS= read -r -d '' a; do args+=("$a"); done <"$work/args"
}

# REQ-CLEAN-01: every conformance case cleans to its expected line.
for input in "$root"/spec/cases/clean/*.in; do
    name=$(basename "$input" .in)
    want=$(cat "${input%.in}.out")
    got=$("$sol" --clean <"$input")
    if [[ $got == "$want" ]]; then pass "REQ-CLEAN-01 $name"; else fail "REQ-CLEAN-01 $name: got [$got] want [$want]"; fi
done

# REQ-CMD-01: the request goes to vazhi ask --fast with a system prompt, after --, and the
# cleaned answer is printed.
rm -f "$work/args"
out=$(STUB_ANSWER=$'```bash\nls -lS\n```' "$sol" -- --list big files)
status=$?
stub_args
if [[ $status -eq 0 && $out == "ls -lS" && ${args[0]} == ask && ${args[1]} == --fast && ${args[2]} == --system && ${args[4]} == -- && ${args[5]} == "--list big files" ]]; then
    pass "REQ-CMD-01 request to vazhi and cleaned answer printed"
else
    fail "REQ-CMD-01 status=$status out=[$out] args=[${args[*]}]"
fi

# REQ-CMD-02: no request, or --init without bash, is bad usage.
"$sol" >/dev/null 2>&1
s1=$?
"$sol" -- "   " >/dev/null 2>&1
s2=$?
"$sol" --init fish >/dev/null 2>&1
s3=$?
if [[ $s1 -eq 2 && $s2 -eq 2 && $s3 -eq 2 ]]; then pass "REQ-CMD-02 usage errors exit 2"; else fail "REQ-CMD-02 got $s1 $s2 $s3"; fi

# REQ-CMD-06: an old bash is refused with a message that says what to install.
out=$(SOL_TEST_BASH_MAJOR=3 "$sol" -- list files 2>"$work/err")
status=$?
if [[ $status -eq 2 && -z $out ]] && grep -q "needs bash 4 or later" "$work/err"; then
    pass "REQ-CMD-06 bash 3 refused"
else
    fail "REQ-CMD-06 status=$status err=[$(cat "$work/err")]"
fi

# REQ-CMD-03: vazhi failing exits 1 with nothing on stdout and vazhi's reason on stderr.
out=$(STUB_STATUS=1 STUB_STDERR="vazhi: every model failed" "$sol" -- list files 2>"$work/err")
status=$?
if [[ $status -eq 1 && -z $out ]] && grep -q "every model failed" "$work/err"; then
    pass "REQ-CMD-03 vazhi failure exits 1, stdout empty"
else
    fail "REQ-CMD-03 status=$status out=[$out]"
fi
out=$(SOL_VAZHI=$work/missing "$sol" -- list files 2>"$work/err")
status=$?
if [[ $status -eq 1 && -z $out ]] && grep -q "vazhi not found" "$work/err"; then
    pass "REQ-CMD-03 missing vazhi exits 1 and says so"
else
    fail "REQ-CMD-03 missing: status=$status out=[$out] err=[$(cat "$work/err")]"
fi

# REQ-CMD-04: an answer with no command line exits 3 with nothing on stdout.
out=$(STUB_ANSWER=$'# nothing to do\n\n' "$sol" -- list files 2>/dev/null)
status=$?
if [[ $status -eq 3 && -z $out ]]; then pass "REQ-CMD-04 empty answer exits 3"; else fail "REQ-CMD-04 status=$status out=[$out]"; fi

# REQ-CTX-01: the system prompt names the system with its family, the shell, the directory,
# and the last five history lines, oldest first.
printf 'NAME="Testix"\nPRETTY_NAME="Testix 9"\nID_LIKE=arch\n' >"$work/os-release"
history=$(printf 'cmd%s\n' 1 2 3 4 5 6 7)
prompt=$(SOL_OS_RELEASE=$work/os-release SOL_HISTORY=$history SOL_CWD=/srv/app SOL_SHELL="bash 5.3" "$sol" --dry-run find logs)
expected_tail=$'System: Testix 9 (based on arch)\nShell: bash 5.3\nCurrent directory: /srv/app\nRecent commands, oldest first:\n  cmd3\n  cmd4\n  cmd5\n  cmd6\n  cmd7\n\nfind logs'
if [[ $prompt == *"$expected_tail" && $prompt == *"Reply with the command line only"* ]]; then
    pass "REQ-CTX-01 context block"
else
    fail "REQ-CTX-01 got: $prompt"
fi
prompt=$(SOL_OS_RELEASE=$work/none SOL_HISTORY="" "$sol" --dry-run x)
if [[ $prompt == *"System: $(uname -s)"* && $prompt != *"Recent commands"* ]]; then
    pass "REQ-CTX-01 no os-release and no history"
else
    fail "REQ-CTX-01 fallback got: $prompt"
fi

# REQ-CTX-01: SOL_HISTORY in the form of `history N` loses its numbers, and a command spanning
# lines is one entry.
history=$'    7  git status\n    8* echo \'two\nlines\'\n    9  ls'
prompt=$(SOL_HISTORY=$history "$sol" --dry-run x)
if [[ $prompt == *$'oldest first:\n  git status\n  echo \'two lines\'\n  ls\n'* ]]; then
    pass "REQ-CTX-01 numbered history"
else
    fail "REQ-CTX-01 numbered history got: $prompt"
fi

# REQ-CTX-02: history lines that look like secrets never reach vazhi; ordinary ones do. Each
# safe line is sent alone after every secret line, so the case files can grow freely.
drop=$(cat "$root/spec/cases/secret/drop.txt")
ctx02=1
while IFS= read -r safe; do
    [[ -n $safe ]] || continue
    rm -f "$work/args"
    STUB_ANSWER=ls SOL_HISTORY="$drop"$'\n'"$safe" "$sol" -- list >/dev/null
    stub_args
    system=${args[3]}
    [[ $system == *$'oldest first:\n  '"$safe"* ]] || { fail "REQ-CTX-02 dropped a safe line: $safe"; ctx02=0; }
    while IFS= read -r line; do
        [[ -n $line && $system == *"$line"* ]] && { fail "REQ-CTX-02 leaked: $line"; ctx02=0; }
    done <<<"$drop"
done <"$root/spec/cases/secret/keep.txt"
((ctx02)) && pass "REQ-CTX-02 secret lines dropped, others kept"

# REQ-CMD-05: a command word that an alias replaces runs as `command <name>`; other words,
# shortcuts (g) and quoted uses stay. Aliases: ls replaces a command, g does not.
aliases=$'alias ls=\'eza -lh --token-ABC123\'\nalias g=\'git\'\nalias c++=\'clang++\''
while IFS=$'\t' read -r input want; do
    got=$(STUB_ANSWER=$input SOL_ALIASES=$aliases "$sol" -- x)
    if [[ $got == "$want" ]]; then pass "REQ-CMD-05 [$input]"; else fail "REQ-CMD-05 [$input]: got [$got] want [$want]"; fi
done <"$root/spec/cases/unalias/cases.tsv"
# zsh prints aliases as name=value, with quotes only when needed.
got=$(STUB_ANSWER='ls -lt | tail -1' SOL_ALIASES=$'g=git\nls=\'eza -lh\'\nrun-help=man' "$sol" -- x)
if [[ $got == "command ls -lt | tail -1" ]]; then pass "REQ-CMD-05 zsh alias format"; else fail "REQ-CMD-05 zsh alias format: got [$got]"; fi
rm -f "$work/args"
STUB_ANSWER=ls SOL_ALIASES=$aliases "$sol" -- x >/dev/null
stub_args
if [[ ${args[3]} != *eza* && ${args[3]} != *token-ABC123* ]]; then
    pass "REQ-CMD-05 alias values never reach vazhi"
else
    fail "REQ-CMD-05 alias value sent: ${args[3]}"
fi

# REQ-CTX-03: the directories in the current directory, not hidden ones or files, are named.
mkdir -p "$work/here/Downloads" "$work/here/src" "$work/here/.cache" "$work/here/My Files"
: >"$work/here/notes.txt"
prompt=$(SOL_CWD=$work/here "$sol" --dry-run x)
if [[ $prompt == *$'\nDirectories here: Downloads \'My Files\' src\n'* ]]; then
    pass "REQ-CTX-03 directory names"
else
    fail "REQ-CTX-03 got: $prompt"
fi
prompt=$(SOL_CWD=$work/here/src "$sol" --dry-run x)
if [[ $prompt != *"Directories here"* ]]; then pass "REQ-CTX-03 no line without directories"; else fail "REQ-CTX-03 empty: $prompt"; fi

# REQ-WIDGET-01: the widget code parses and binds Ctrl+G to __sol_widget.
init=$("$sol" --init bash)
if bash -n <<<"$init" && [[ $init == *"bind -x '\"\\C-g\": __sol_widget'"* ]]; then
    pass "REQ-WIDGET-01 widget parses and binds Ctrl+G"
else
    fail "REQ-WIDGET-01 widget: $init"
fi

# REQ-PERF-01: sol's own time around an instant vazhi, median of 11 runs, under 100 ms.
times=()
for _ in $(seq 11); do
    t0=$(date +%s%N)
    STUB_ANSWER=ls SOL_HISTORY=$history "$sol" -- list files >/dev/null
    times+=($((($(date +%s%N) - t0) / 1000000)))
done
median=$(printf '%s\n' "${times[@]}" | sort -n | sed -n 6p)
if ((median < 100)); then pass "REQ-PERF-01 median ${median} ms"; else fail "REQ-PERF-01 median ${median} ms, over 100"; fi

if ((failures)); then
    echo "ERROR $failures sol test(s) failed; see the FAIL lines above"
    exit 1
fi
echo "all sol tests passed"
