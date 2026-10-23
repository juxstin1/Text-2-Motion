"""Run holdout prompts through the local model and log the results.

Usage:
    python tools/run_experiment.py --url http://127.0.0.1:8090/v1                       # 3 prompts, 3-shot, 2 repairs
    python tools/run_experiment.py --ids shape-drop-bounce record-stamp --shots 0 3 --fix 2

Each run calls run_local.py (saves every attempt as a pending entry with gen stats in meta.json).
Log: docs/experiments/<date>-run.log
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent
DEFAULT_IDS = ["shape-drop-bounce", "record-stamp", "cta-button-pop"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="+", default=DEFAULT_IDS, help="holdout entry ids whose prompt.txt to use")
    ap.add_argument("--shots", nargs="+", type=int, default=[3], choices=[0, 3])
    ap.add_argument("--fix", type=int, default=2, help="repair rounds per run (2 = 3 attempts)")
    ap.add_argument("--url", default="http://127.0.0.1:8090/v1")
    ap.add_argument("--think", choices=["on", "off"], default="on")
    args = ap.parse_args()

    log = BANK / "docs" / "experiments" / f"{time.strftime('%Y-%m-%d')}-run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as f:
        for hid in args.ids:
            prompt = (BANK / "entries" / hid / "prompt.txt").read_text(encoding="utf-8").strip()
            for shots in args.shots:
                head = f"=== {hid}  shots={shots}  {time.strftime('%H:%M:%S')}"
                print(head, flush=True); f.write(head + "\n"); f.flush()
                cmd = [sys.executable, str(BANK / "tools" / "run_local.py"), prompt, "--shots", str(shots),
                       "--fix", str(args.fix), "--vision", "--url", args.url, "--think", args.think]
                proc = subprocess.Popen(cmd, cwd=BANK, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8")
                for line in proc.stdout:
                    print(line, end="", flush=True); f.write(line); f.flush()
                proc.wait()
        f.write(f"=== done {time.strftime('%H:%M:%S')}\n")
    print(f"log: {log}")


if __name__ == "__main__":
    main()
