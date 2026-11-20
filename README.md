# Sol

Type what you want done at the bash or zsh prompt, press Ctrl+G, and the line becomes the command. Nothing runs until you press Enter.

What you type, then press Ctrl+G:

```text
find pdfs over 10mb in downloads from this week
```

What the line becomes, ready for Enter:

```text
find ~/Downloads -type f -name "*.pdf" -size +10M -mtime -7
```

Sol asks [vazhi](https://github.com/itsgg/vazhi)'s fast list of free models, so an answer usually takes under a second. It sends the request with your system, shell, current directory and last five commands; commands that look like they hold a key, token or password are left out. If no model answers, your words stay on the line.

Sol is Tamil for "say".

## Install

Sol needs bash 5 or zsh 5, and vazhi 0.2 or later, which the first block installs. Keys are set as vazhi's README says; Groq's free key gives the fastest answers.

```bash
npm install -g --legacy-peer-deps @itsgg/vazhi
git clone https://github.com/itsgg/sol ~/.local/share/sol-src
mkdir -p ~/.local/bin
ln -sf ~/.local/share/sol-src/sol ~/.local/bin/sol
```

Then, for bash:

```bash
echo 'command -v sol >/dev/null && eval "$(sol --init bash)"' >> ~/.bashrc
```

Or, for zsh:

```bash
echo 'command -v sol >/dev/null && eval "$(sol --init zsh)"' >> ~/.zshrc
```

Open a new terminal. `~/.local/bin` must be on your PATH, as it is on most Linux systems. The script itself needs bash 4 or later; on macOS, `brew install bash`.

Ctrl+G replaces the default abort binding of readline and of zsh's line editor.

## Use

`sol -- REQUEST` prints the command for a request, for scripts and other shells. `sol --dry-run REQUEST` prints what would be sent. Exit status: 0 a command was printed, 1 no model answered, 2 bad usage, 3 the answer held no command.

- [SEED.md](SEED.md): purpose, principles, decisions and evidence.
- [SPEC.md](SPEC.md): the contract the code is built against.
- [AGENTS.md](AGENTS.md): how agents take and finish work; [tasks/](tasks/) holds the work.
- `tools/gate`: the gate every change passes. `tools/land`: lands a branch.

## License

MIT
