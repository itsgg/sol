#!/usr/bin/env bash
# CI setup for Sol's tests of record: the zsh widget tests need zsh (SPEC REQ-WIDGET-05).
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq zsh
