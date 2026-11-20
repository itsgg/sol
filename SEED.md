# Sol: Product Founding Brief

Created: 2026-11-20. Updated: 2026-11-20. Status: current founding brief. Owner: GG.

This document defines Sol's purpose, intended behavior and decision boundaries. SPEC.md and the tasks derive from it. The founder intent below is established; the design in sections 4 and 5 is a product proposal, open to revision as use teaches.

Labels: founder intent, product proposal, evidence, hypothesis, open decision. Principles are P1, decisions D1, open choices O1, evidence R1; a number is never reused.

## 1. Purpose and ambition

Sol turns what you mean into the shell command that does it, on the line where you were going to type it. You type a request at the bash prompt in plain words, press Ctrl+G, and the line becomes a command you can read, edit and run with Enter. Nothing runs until you press Enter.

Founder intent (GG, 2026-11-20): replace lxask, which was too slow, with "a better text to shell command", built "as a new personal project very cleanly, test it and bind to ctrl+g", on vazhi as "a modular CLI", public under MIT, sending the last few commands as context.

Sol is Tamil for "say" or "word": you say it, and it becomes the command.

Terms. A request is the text on the prompt line when Ctrl+G is pressed. A command is the single command line Sol puts in its place. Context is what Sol sends with the request: the operating system, the shell, the current directory and recent history.

## 2. People and problems

The user is GG at his bash prompt on Arch Linux (Omarchy), who knows what he wants done and not always the flags, or who wants a long pipeline without typing it. Today he either leaves the terminal to search or ask a chat model, or uses a tool that answers too slowly to stay in the flow of typing.

Evidence (R1): lxask, a local 1.5B model, took 13 s for a cold answer and 6.5 to 8.2 s warm on this laptop, and answered "list files by size" with `ls -lS --recursive` and a literal `path/to/directory` placeholder.

Sol takes responsibility for proposing one good command quickly. It does not run commands, explain them at length, hold a conversation or manage a shell session.

## 3. Opportunity and timing

Evidence (R2): on 2026-11-20 Groq's free tier answered short command-generation requests in 0.13 to 0.62 s through vazhi's fast list, end to end 0.5 to 0.7 s from a fresh `vazhi ask` process. Free hosted models are now fast enough that a hotkey can wait for one.

Evidence (R3): vazhi, GG's free LLM router, now has a command line (`vazhi ask --fast`) that routes across free providers with shared cooldowns and a second model asked when the first is slow. Sol needs no router of its own.

The assumption most likely to change the opportunity: free tiers change their limits often. vazhi absorbs that; Sol depends only on `vazhi ask`.

## 4. The product experience

GG types `find all pdfs over 10mb in downloads modified this week`, presses Ctrl+G, and within about a second the line reads `find ~/Downloads -name '*.pdf' -size +10M -mtime -7`. He edits a number and presses Enter. Ctrl+G again on a command line rewrites it to match its words, so `tar the logs folder` followed by Ctrl+G gives the tar command.

He types `do that again but for the src folder` after running a grep: recent history lets Sol fill in the grep.

When no model answers (no network, every free model cooling), his words stay on the line untouched, and one short line under the prompt says why. When the request needs a value Sol cannot know, the command holds a visible placeholder such as `<branch>` rather than a guess.

## 5. Core product logic

Product proposal. The bash widget reads the line and the last few history lines and calls `sol` with them. `sol` drops history lines that look like they carry secrets, builds a system prompt with the context, and calls `vazhi ask --fast`. It cleans the answer to one command line (removes code fences, a leading `$ `, comments and blank lines) and prints it. The widget puts it on the line with the cursor at the end. If anything fails, the line is left as it was.

The model is vazhi's to choose; Sol never names one. Sol's own logic is the prompt, the context and the cleaning, and these are what its tests pin down.

## 6. Evidence and proof

Sol works when, in GG's daily use, the command on the line is the one he meant, or one small edit from it, and arrives before he would have finished typing it. The tests check what Sol controls: the cleaning, the context, secret filtering, the widget's handling of the line, and failure leaving the line intact. Answer quality is checked by a small set of reference requests run live against vazhi, read by eye, not gated, since free models change nightly.

## 7. Strategy and differentiation

Alternatives: lxask (local, slow, removed), shell_gpt's Ctrl+L integration (R4) and llm-cmd (R5), both tied to one provider's key. Sol is thin on purpose: vazhi carries routing, free providers and cooldowns, and Sol carries the shell experience. The strongest substitute is asking Claude Code or pi in another pane; Sol wins only by being on the line, in under a second.

## 8. Business and distribution

None. A personal tool, public under MIT so others can read and use it. No users beyond GG are assumed.

## 9. Scope and progression

First release: bash only, the Ctrl+G widget, `sol` printing one command, context of OS, shell, current directory and the last five history lines, installed on GG's machine with a `~/.local/bin` wrapper and a line in `~/.bashrc`.

Deferred: a fish widget, multi-line scripts, explanations, a confirmation step for dangerous commands, offline fallback.

Reference cases: `spec/cases/clean/` holds model outputs and the command line Sol must make of each (written by hand from the formats seen on 2026-11-20: fences, `$ ` prompts, comments, several lines). `spec/cases/live.tsv` holds reference requests with a pattern for a correct command, for the live, ungated check in `tests/live/eval.py`.

## 10. Principles and tradeoffs

- P1. Never run anything. Sol only edits the line; Enter is always GG's.
- P2. Fast beats thorough. A one-second answer that needs an edit beats a ten-second perfect one; the fast list and its hedge are vazhi's, and Sol adds nothing slow to the path.
- P3. Fail to the original line. Any failure leaves the request where it was, with one short reason.
- P4. Thin over vazhi. Routing, keys and providers stay in vazhi; Sol never calls a provider itself.
- P5. Send no secrets. History lines that look like they carry a key, token or password are dropped before anything leaves the machine.

P1 and P3 win over every other principle.

## 11. Success, risks and unknowns

Success: GG keeps Ctrl+G bound after a week of use. Risks: the free fast list goes slow or down (vazhi falls back to slower models; visible as answers past 3 s); a model returns prose or several commands (the cleaning handles the formats seen; new formats become cases); a secret in history slips past the filter (the filter is a heuristic, P5 limits what is sent, not what is typed).

## 12. Decision authority and sources

Decisions:

- D1. Bash widget on Ctrl+G, replacing lxask's binding (GG, 2026-11-20).
- D2. Models through `vazhi ask --fast`, never directly (GG, 2026-11-20: vazhi as a modular CLI first).
- D3. Context includes recent history, filtered for secrets (GG, 2026-11-20).
- D4. Written in bash, one script plus the widget it prints; tests in bash with a stub `vazhi`. Product proposal: the work is reading a line, building a prompt and cleaning text, and a node or python process would double the start-up cost P2 counts.

- D5. A zsh widget beside the bash one, and a plain refusal on bash older than 4 (GG, 2026-11-20, "fix those in order" after the review of what is specific to his machine).

Open:

- O1. zsh and fish widgets. zsh settled 2026-11-20: GG asked for Sol to be usable beyond his machine, and zsh is the common second shell (D5). fish stays open; next action: none until someone asks.

Working choices at creation, open to GG's change: name Sol (Tamil "say", "word"); repository itsgg/sol, public, MIT.

What the first SPEC must settle: the interface between the widget and `sol` (arguments, environment variables for history and directory, exit codes, stdout and stderr); the exact system prompt and context block; the cleaning rules as conformance cases; the secret filter's patterns; how `sol` finds `vazhi` and how tests stub it; and what the widget does to READLINE_LINE and READLINE_POINT on success and on failure.

Downstream work cites this seed by section and ID, keeps its principles, and surfaces a conflict with them to GG before acting on it.

Evidence register:

- R1. lxask 1.2.0 timings and answers, measured on this laptop by Claude Code, 2026-11-20. Limit: three requests, one machine.
- R2. Latency probe of eleven free models, three requests each, and three `vazhi ask --fast` runs, 2026-11-20. Limit: one evening, one network; free-tier latency varies by hour.
- R3. vazhi command line, branch cli, 2026-11-20, https://github.com/itsgg/vazhi. Limit: new; under review at writing.
- R4. shell_gpt README: shell integration for bash and zsh, Ctrl+L replaces the line with a suggested command, https://github.com/TheR1D/shell_gpt, accessed 2026-11-20.
- R5. llm-cmd: generate a command, review and edit it, Enter to run, https://github.com/simonw/llm-cmd, accessed 2026-11-20.
- R6. GNU Bash manual, Bash Variables: READLINE_LINE and READLINE_POINT hold the line and cursor for `bind -x` commands, and bash applies changes to them, https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html, accessed 2026-11-20.
