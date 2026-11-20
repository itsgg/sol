# Sol

Type what you want done at the bash prompt, press Ctrl+G, and the line becomes the command. Nothing runs until you press Enter.

```
$ find pdfs over 10mb in downloads from this week      <Ctrl+G>
$ find ~/Downloads -type f -name "*.pdf" -size +10M -mtime -7
```

Sol asks [vazhi](https://github.com/itsgg/vazhi)'s fast list of free models, so an answer usually takes under a second. It sends the request with your system, shell, current directory and last five commands; commands that look like they hold a key, token or password are left out. If no model answers, your words stay on the line.

Sol is Tamil for "say".

## Install

Sol needs bash 5 and vazhi 0.2 or later (`npm install -g @itsgg/vazhi`; keys as in vazhi's README, Groq's free key for the fastest answers).

```bash
git clone https://github.com/itsgg/sol ~/.local/share/sol-src
ln -s ~/.local/share/sol-src/sol ~/.local/bin/sol
echo 'command -v sol >/dev/null && eval "$(sol --init bash)"' >> ~/.bashrc
```

Ctrl+G replaces readline's default abort binding.

## Use

`sol -- REQUEST` prints the command for a request, for scripts and other shells. `sol --dry-run REQUEST` prints what would be sent. Exit status: 0 a command was printed, 1 no model answered, 2 bad usage, 3 the answer held no command.

- [SEED.md](SEED.md): purpose, principles, decisions and evidence.
- [SPEC.md](SPEC.md): the contract the code is built against.
- [AGENTS.md](AGENTS.md): how agents take and finish work; [tasks/](tasks/) holds the work.
- `tools/gate`: the gate every change passes. `tools/land`: lands a branch.

## License

MIT
