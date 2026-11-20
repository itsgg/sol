#!/usr/bin/env bash
# CI setup for Sol's tests of record: the zsh widget tests need zsh (SPEC REQ-WIDGET-05).
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq zsh
# The screen tests run pyte through uv (SPEC REQ-WIDGET-06).
command -v pipx >/dev/null || sudo apt-get install -y -qq pipx
pipx install uv >/dev/null
