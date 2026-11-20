# 0002: Aliased commands and directory names

Status: review
Depends on: 0001
Spec: REQ-CMD-05, REQ-CTX-03, REQ-WIDGET-02
Goal: commands work in a shell where ls runs eza, and paths match the directories that exist (change 0002).

Acceptance:
- run: `shellcheck sol tests/acceptance/sol.sh`
- run: `tests/acceptance/sol.sh`
- run: `python3 -I tests/acceptance/widget.py`

## Log

- 2026-11-20: created from GG's failing requests ("list bak files", "list the oldest files").
- 2026-11-20: built. Live, from ~ with GG's aliases: "list the oldest files" gave `command ls -lt` and a find pipeline on two runs, "show the 5 newest files in downloads" gave `command ls -lt Downloads | head -n 6`, "list bak files" gave `find . -name "*.bak"`; each ran.
- 2026-11-20: prompt measured, 5 runs per request on GG's three ("List all hidden files", "List all .bak files", "Which is the oldest file in this dir") in a directory with known answers. The find line alone: GPT-OSS 120B 10/15, Qwen3.8 27B 6/15. Four worked examples and a rule for "here" against "all": GPT-OSS 120B 15/15, Qwen 11/15. The examples replace the find line; vazhi's fast list puts GPT-OSS 120B first.
