#!/usr/bin/env bash
# sol: plain words to one shell command, through vazhi's fast list. It prints the command and
# never runs it (SEED P1). SPEC.md section 7 fixes every interface below.
set -o pipefail

SOL_VERSION=0.1.0
HISTORY_LINES=5

usage() {
    cat <<'EOF'
usage: sol [--] REQUEST...      print one command line for REQUEST
       sol --init bash          print the Ctrl+G widget: eval "$(sol --init bash)" in ~/.bashrc
       sol --dry-run REQUEST... print what would be sent to vazhi, and send nothing
       sol --clean              clean a model's answer on standard input to one command line

Context comes from SOL_HISTORY (recent commands: `history N` output, or one per line), SOL_CWD (default: the
current directory) and SOL_SHELL (default: bash and its version). SOL_VAZHI names the
vazhi command (default: vazhi).

Exit status: 0 a command was printed, 1 no model answered, 2 bad usage, 3 the answer
held no command.
EOF
}

# The operating system's name from os-release (SOL_OS_RELEASE in tests), with the family it
# is based on, so a derivative's package manager is known: "Omarchy (based on arch)".
sol_os() {
    local name="" like="" line value file=${SOL_OS_RELEASE:-/etc/os-release}
    if [[ -r $file ]]; then
        while IFS= read -r line; do
            value=${line#*=}
            value=${value#\"}
            value=${value%\"}
            case $line in
                PRETTY_NAME=*) name=$value ;;
                ID_LIKE=*) like=$value ;;
            esac
        done <"$file"
    fi
    name=${name:-$(uname -s)}
    if [[ -n $like ]]; then
        printf '%s (based on %s)\n' "$name" "$like"
    else
        printf '%s\n' "$name"
    fi
}

# Whether a history line looks like it carries a secret (SEED P5): a word that names one, or a
# long run of letters and digits mixed, as keys and tokens are.
sol_secret() {
    local line=${1,,} word
    case $line in
        *key* | *token* | *secret* | *passw* | *passphrase* | *credential* | *bearer* | *authorization* | *auth=* | *cookie* | *private*)
            return 0 ;;
    esac
    for word in ${1//[^A-Za-z0-9_+=-]/ }; do
        if ((${#word} >= 24)) && [[ $word == *[0-9]* && $word == *[A-Za-z]* ]]; then
            return 0
        fi
    done
    return 1
}

# The commands in SOL_HISTORY, one per line. SOL_HISTORY is either `history N` output, where
# each command starts with its number and a multi-line command's later lines do not, or plain
# lines, one command each. Prints the last HISTORY_LINES commands without secrets, trimmed,
# oldest first, a multi-line command joined with spaces.
sol_history() {
    local line entries=() numbered=0 first=1 entry
    while IFS= read -r line; do
        if ((first)) && [[ -n ${line//[[:space:]]/} ]]; then
            [[ $line =~ ^[[:space:]]*[0-9]+\*?[[:space:]] ]] && numbered=1
            first=0
        fi
        if ((numbered)) && [[ $line =~ ^[[:space:]]*[0-9]+\*?[[:space:]]+(.*)$ ]]; then
            entries+=("${BASH_REMATCH[1]}")
        elif ((numbered)) && ((${#entries[@]})); then
            entries[-1]+=" $line"
        else
            entries+=("$line")
        fi
    done <<<"${SOL_HISTORY:-}"
    local kept=()
    for entry in "${entries[@]}"; do
        entry="${entry#"${entry%%[![:space:]]*}"}"
        entry="${entry%"${entry##*[![:space:]]}"}"
        [[ -n $entry ]] || continue
        sol_secret "$entry" && continue
        kept+=("$entry")
    done
    local start=$((${#kept[@]} - HISTORY_LINES))
    ((start < 0)) && start=0
    for entry in "${kept[@]:start}"; do
        printf '%s\n' "$entry"
    done
}

sol_system_prompt() {
    local shell=${SOL_SHELL:-bash ${BASH_VERSION%%[^0-9.]*}} cwd=${SOL_CWD:-$PWD} history
    history=$(sol_history)
    cat <<EOF
You turn a request typed at a shell prompt into one command line for that shell.
Reply with the command line only: no explanation, no code fence, no comments, no leading \$.
Write one line; join steps with && or a pipe.
If the request is already a command, return it corrected, or unchanged when it is right.
When the command needs a value the request does not give, write it as <name> for the user to fill in.
Use the tools that come with the system below, or those the request names. Add sudo only when the task needs root.
The current directory is the one below: use relative paths for things in it and ~ for the home directory.

System: $(sol_os)
Shell: $shell
Current directory: $cwd
EOF
    if [[ -n $history ]]; then
        printf 'Recent commands, oldest first:\n'
        while IFS= read -r line; do printf '  %s\n' "$line"; done <<<"$history"
    fi
}

# A model's answer on stdin to one command line on stdout (spec/cases/clean/).
sol_clean() {
    local text line in_fence=0 found_fence=0 lines=() fenced=() out="" joiner=""
    text=$(cat)
    text=${text//$'\r'/}
    while IFS= read -r line; do
        if [[ $line =~ ^[[:space:]]*\`\`\` ]]; then
            if ((in_fence)); then
                in_fence=0
                ((found_fence)) && break
            else
                in_fence=1
                found_fence=1
            fi
            continue
        fi
        if ((in_fence)); then fenced+=("$line"); else lines+=("$line"); fi
    done <<<"$text"
    ((found_fence)) && lines=("${fenced[@]}")
    for line in "${lines[@]}"; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z $line || $line == \#* ]] && continue
        [[ $line == '$ '* ]] && line=${line#'$ '}
        # A line wrapped in backticks and holding no others, as in `ls -lS`.
        if [[ $line == \`*\` && ${#line} -ge 2 && ${line:1:${#line}-2} != *\`* ]]; then
            line=${line#\`}
            line=${line%\`}
        fi
        [[ -n $line ]] || continue
        out+="$joiner$line"
        if [[ $out == *\\ ]]; then
            out=${out%\\}
            out="${out%"${out##*[![:space:]]}"}"
            joiner=" "
        elif [[ $out == *'|' || $out == *'&&' || $out == *'||' ]]; then
            joiner=" "
        else
            joiner=" && "
        fi
    done
    [[ -n $out ]] || return 3
    printf '%s\n' "$out"
}

sol_init() {
    local self
    self=$(readlink -f "${BASH_SOURCE[0]}")
    case ${1:-} in
        bash) ;;
        *)
            echo "sol: --init takes bash" >&2
            return 2
            ;;
    esac
    cat <<EOF
# sol: type what you want done, press Ctrl+G, and the line becomes the command.
# Nothing runs until you press Enter. In ~/.bashrc: eval "\$(sol --init bash)"
__sol_widget() {
    local request=\$READLINE_LINE command
    [[ -n \${request//[[:space:]]/} ]] || return 0
    # history, not fc: inside bind -x, fc -l leaves out the latest command.
    command=\$(SOL_HISTORY="\$(HISTTIMEFORMAT= history $HISTORY_LINES)" SOL_CWD="\$PWD" SOL_SHELL="bash \${BASH_VERSION%%[^0-9.]*}" $(printf '%q' "$self") -- "\$request") || return 0
    [[ -n \$command ]] || return 0
    READLINE_LINE=\$command
    # bash 5 counts READLINE_POINT in characters, as \${#} does in a UTF-8 locale.
    READLINE_POINT=\${#READLINE_LINE}
}
bind -x '"\C-g": __sol_widget'
EOF
}

main() {
    case ${1:-} in
        -h | --help)
            usage
            return 0
            ;;
        --version)
            echo "$SOL_VERSION"
            return 0
            ;;
        --init)
            sol_init "${2:-}"
            return
            ;;
        --clean)
            sol_clean
            return
            ;;
    esac
    local dry=0
    if [[ ${1:-} == --dry-run ]]; then
        dry=1
        shift
    fi
    [[ ${1:-} == -- ]] && shift
    local request="$*"
    request="${request#"${request%%[![:space:]]*}"}"
    request="${request%"${request##*[![:space:]]}"}"
    if [[ -z $request ]]; then
        usage >&2
        return 2
    fi
    local system answer
    system=$(sol_system_prompt)
    if ((dry)); then
        printf '%s\n\n%s\n' "$system" "$request"
        return 0
    fi
    answer=$("${SOL_VAZHI:-vazhi}" ask --fast --system "$system" -- "$request") || {
        local status=$?
        # vazhi has already said why on stderr; 127 means it is not installed.
        ((status == 127)) && echo "sol: vazhi not found; install it or set SOL_VAZHI" >&2
        return 1
    }
    printf '%s\n' "$answer" | sol_clean || {
        echo "sol: the answer held no command" >&2
        return 3
    }
}

main "$@"
