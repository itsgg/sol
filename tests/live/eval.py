#!/usr/bin/env python3
"""Live eval of sol's answers through the real vazhi (SPEC.md section 9). Never gated: free
models change nightly, and it needs the network and vazhi's keys.

Each request in spec/cases/live.tsv runs RUNS times from a scratch directory that holds
Downloads and src, with ls aliased to eza; an answer passes when it matches the case's regex and
not its must-not regex. Requests are paced to stay inside Groq's 30 a minute.

Usage: tests/live/eval.py [RUNS]   (default 3; prints a score per request and in total)
"""
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOL = os.path.join(ROOT, "sol")
CASES = os.path.join(ROOT, "spec", "cases", "live.tsv")
PACE = 2.2  # seconds between requests


def cases():
    with open(CASES) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            request, good, *bad = line.split("\t")
            yield request, re.compile(good), re.compile(bad[0]) if bad and bad[0] else None


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with tempfile.TemporaryDirectory() as here:
        for d in ("Downloads", "src"):
            os.mkdir(os.path.join(here, d))
        env = dict(os.environ, SOL_CWD=here, SOL_ALIASES="alias ls='eza -lh --group-directories-first'", SOL_HISTORY="")
        total = passed = 0
        for request, good, bad in cases():
            hits, misses, times = 0, [], []
            for _ in range(runs):
                start = time.time()
                out = subprocess.run([SOL, "--", request], cwd=here, env=env, capture_output=True, text=True)
                times.append(time.time() - start)
                answer = out.stdout.strip()
                ok = out.returncode == 0 and good.search(answer) and not (bad and bad.search(answer))
                hits += 1 if ok else 0
                if not ok:
                    misses.append(answer or f"(exit {out.returncode}: {out.stderr.strip()[:60]})")
                time.sleep(PACE)
            total += runs
            passed += hits
            slowest = max(times)
            line = f"{hits}/{runs}  {slowest:4.1f}s max  {request}"
            if misses:
                line += "\n      missed: " + " | ".join(sorted(set(misses))[:2])
            print(line, flush=True)
        print(f"total {passed}/{total}")


if __name__ == "__main__":
    main()
