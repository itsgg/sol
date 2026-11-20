#!/usr/bin/env bash
# sol: plain words to one shell command, through vazhi's fast list. It prints the command and
# never runs it (SEED P1). SPEC.md section 7 fixes every interface below.
set -o pipefail

SOL_VERSION=0.3.0
HISTORY_LINES=5

usage() {
    cat <<'EOF'
usage: sol [--] REQUEST...      print one command line for REQUEST
       sol --init bash|zsh      print the Ctrl+G widget: eval "$(sol --init bash)" in ~/.bashrc,
                                or eval "$(sol --init zsh)" in ~/.zshrc
       sol --dry-run REQUEST... print what would be sent to vazhi, and send nothing
       sol --clean              clean a model's answer on standard input to one command line

Context comes from SOL_HISTORY (recent commands: `history N` output, or one per line), SOL_ALIASES
(`alias` output), SOL_CWD (default: the
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

# The names in SOL_ALIASES (`alias` output) that replace a command on PATH, such as ls when it
# runs eza. Shortcuts like g='git' replace nothing. Only names are used; values never leave.
sol_alias_names() {
    local line name
    while IFS= read -r line; do
        # Names with only letters, digits, _ and -, so a name is safe inside a regex.
        # bash prints `alias name='value'`, zsh `name=value`.
        [[ $line =~ ^(alias\ )?([A-Za-z0-9_-]+)= ]] || continue
        name=${BASH_REMATCH[2]}
        type -P -- "$name" >/dev/null 2>&1 && printf '%s\n' "$name"
    done <<<"${SOL_ALIASES:-}"
}

# Models write the original program's flags, so a command word an alias replaces is run as
# `command <name>`: at the start and after |, ;, &, ( or `, up to a space, an operator, a
# redirect, ) or ` or the end. Quoted text is not parsed.
sol_unalias() {
    local cmd=$1 name re
    while IFS= read -r name; do
        [[ -n $name ]] || continue
        re="(^|[|;&(\`][[:space:]]*)$name([[:space:]|;&)\`<>].*|$)"
        local out="" rest=$cmd
        # Each match leaves the character after the name in rest, so `ls; ls` matches twice.
        while [[ $rest =~ $re ]]; do
            out+="${rest:0:${#rest}-${#BASH_REMATCH[0]}}${BASH_REMATCH[1]}command $name"
            rest=${BASH_REMATCH[2]}
        done
        cmd=$out$rest
    done < <(sol_alias_names)
    printf '%s\n' "$cmd"
}

# Up to 40 directory names in the current directory, not hidden, so paths are spelled right.
sol_dirs() {
    local cwd=${SOL_CWD:-$PWD} d names=() 
    for d in "$cwd"/*/; do
        [[ -d $d ]] || continue
        d=${d%/}
        d=${d##*/}
        [[ $d == *[[:space:]]* ]] && d="'$d'"
        names+=("$d")
        ((${#names[@]} >= 40)) && break
    done
    local IFS=" "
    printf '%s\n' "${names[*]}"
}

sol_system_prompt() {
    local shell=${SOL_SHELL:-bash ${BASH_VERSION%%[^0-9.]*}} cwd=${SOL_CWD:-$PWD} history dirs line
    history=$(sol_history)
    dirs=$(sol_dirs)
    cat <<EOF
You turn a request typed at a shell prompt into one command line for that shell.
Reply with the command line only: no explanation, no code fence, no comments, no leading \$.
Write one line; join steps with && or a pipe.
If the request is already a command, return it corrected, or unchanged when it is right.
When the command needs a value the request does not give, write it as <name> for the user to fill in.
Use the tools that come with the system below, or those the request names. Add sudo only when the task needs root.
The current directory is the one below: use relative paths for things in it and ~ for the home directory.
"Here", "in this dir" or "in this folder" means the current directory only, not below it; "all" or no place, for files named by type or pattern, means the current directory and below.
Examples:
  show the largest file here -> ls -S | head -n 1
  list python files -> find . -type f -name '*.py'
  list hidden directories in this folder -> find . -maxdepth 1 -type d -name '.*' ! -name .
  newest log in this dir -> ls -t *.log | head -n 1

System: $(sol_os)
Shell: $shell
Current directory: $cwd
EOF
    [[ -n $dirs ]] && printf 'Directories here: %s\n' "$dirs"
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
    self=$(printf '%q' "$(readlink -f "${BASH_SOURCE[0]}")")
    case ${1:-} in
        bash)
            cat <<EOF
# sol: type what you want done, press Ctrl+G, and the line becomes the command.
# Nothing runs until you press Enter. In ~/.bashrc: eval "\$(sol --init bash)"
__sol_widget() {
    local request=\$READLINE_LINE command
    [[ -n \${request//[[:space:]]/} ]] || return 0
    # history, not fc: inside bind -x, fc -l leaves out the latest command.
    # SOL_FEEDBACK: sol draws a spinner on this line while it waits; bash redraws the line after.
    # Its stderr is kept apart, so a failure's reason prints on its own line above the prompt.
    if ! command=\$(SOL_FEEDBACK=1 SOL_ALIASES="\$(alias)" SOL_HISTORY="\$(HISTTIMEFORMAT= history $HISTORY_LINES)" SOL_CWD="\$PWD" SOL_SHELL="bash \${BASH_VERSION%%[^0-9.]*}" $self -- "\$request") || [[ -z \$command ]]; then
        return 0
    fi
    READLINE_LINE=\$command
    # bash 5 counts READLINE_POINT in characters, as \${#} does in a UTF-8 locale.
    READLINE_POINT=\${#READLINE_LINE}
}
bind -x '"\C-g": __sol_widget'
EOF
            ;;
        zsh)
            cat <<EOF
# sol: type what you want done, press Ctrl+G, and the line becomes the command.
# Nothing runs until you press Enter. In ~/.zshrc: eval "\$(sol --init zsh)"
__sol_widget() {
    local request=\$BUFFER command
    [[ -n \${request//[[:space:]]/} ]] || return 0
    local output
    # SOL_FEEDBACK: sol draws a spinner on this line while it waits. Its stdout and stderr are
    # taken together: the command when it succeeds, the reason when it fails.
    output=\$(SOL_FEEDBACK=1 SOL_ALIASES="\$(alias)" SOL_HISTORY="\$(fc -ln -$HISTORY_LINES 2>/dev/null)" SOL_CWD="\$PWD" SOL_SHELL="zsh \$ZSH_VERSION" $self -- "\$request" 2>&1)
    if [[ \$? -ne 0 || -z \$output ]]; then
        zle reset-prompt
        [[ -n \$output ]] && zle -M "\$output"
        return 0
    fi
    BUFFER=\$output
    CURSOR=\${#BUFFER}
    zle reset-prompt
}
zle -N __sol_widget
bindkey '^G' __sol_widget
EOF
            ;;
        *)
            echo "sol: --init takes bash or zsh" >&2
            return 2
            ;;
    esac
}

# While vazhi answers, a dim spinner with the elapsed time on the terminal's current line:
# `| sol: thinking 1.2s`. Only when the widget asks (SOL_FEEDBACK=1) and a terminal is there;
# the shell redraws its line when the widget returns. Writes to fd 3, the terminal.
sol_spinner() {
    local frames="|/-\\" i=0 start now ms
    # EPOCHREALTIME is bash 5; on bash 4 the time counts in whole seconds.
    start=${EPOCHREALTIME/./}
    start=${start:-$((SECONDS * 1000000))}
    while :; do
        now=${EPOCHREALTIME/./}
        now=${now:-$((SECONDS * 1000000))}
        ms=$(((now - start) / 1000))
        printf '\r\e[2K\e[2m%s sol: thinking %d.%ds\e[0m' "${frames:i++%4:1}" $((ms / 1000)) $((ms % 1000 / 100)) >&3
        sleep 0.1
    done
}

# Ask vazhi, with the spinner when asked for one. vazhi prints only an answer when it succeeds
# and only why when it fails, so one capture holds either; the reason goes to stderr after the
# spinner is cleared, so it stays on screen.
sol_ask() {
    local system=$1 request=$2 spinner="" status=0 answer
    if [[ ${SOL_FEEDBACK:-} == 1 ]] && { exec 3>/dev/tty; } 2>/dev/null; then
        sol_spinner &
        spinner=$!
        trap 'kill "$spinner" 2>/dev/null; printf "\r\e[2K" >&3; exit 130' INT TERM
    fi
    answer=$("${SOL_VAZHI:-vazhi}" ask --fast --system "$system" -- "$request" 2>&1) || status=$?
    if [[ -n $spinner ]]; then
        kill "$spinner" 2>/dev/null
        wait "$spinner" 2>/dev/null
        printf '\r\e[2K' >&3
        trap - INT TERM
        exec 3>&-
    fi
    if ((status)); then
        # 127 is a missing vazhi, which main reports in its own words.
        ((status != 127)) && [[ -n $answer ]] && printf '%s\n' "$answer" >&2
        return "$status"
    fi
    printf '%s' "$answer"
}

main() {
    # bash 4 has the case conversion and arrays sol uses; macOS ships 3.2 as /bin/bash.
    # SOL_TEST_BASH_MAJOR stands in for the running version in tests.
    local major=${SOL_TEST_BASH_MAJOR:-${BASH_VERSINFO[0]}}
    if ((major < 4)); then
        echo "sol: needs bash 4 or later to run; this is bash $major (on macOS: brew install bash)" >&2
        return 2
    fi
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
    answer=$(sol_ask "$system" "$request") || {
        local status=$?
        # vazhi has already said why on stderr; 127 means it is not installed.
        ((status == 127)) && echo "sol: vazhi not found; install it or set SOL_VAZHI" >&2
        return 1
    }
    local command
    command=$(printf '%s\n' "$answer" | sol_clean) || {
        echo "sol: the answer held no command" >&2
        return 3
    }
    sol_unalias "$command"
}

main "$@"
