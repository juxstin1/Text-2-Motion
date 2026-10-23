"""Regression tests for the motion checker.

Usage:
    python tools/test_checker.py            # render every fixture and check its report

Each fixtures/<name>/ holds a frozen anim.html and expect.json:
    must        strings report.txt has to contain
    must_not    strings it must not contain
    known_gap   true = a blind spot we know about; failing is expected (XFAIL), passing means it's fixed (XPASS)
    why         where the case came from

Whenever a model breaks something in a new way and the checker misses it, freeze that anim.html here.
Every checker change must keep all non-gap fixtures passing. Exit code 1 on any FAIL or XPASS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

FIXTURES = render.BANK / "fixtures"


def check(fx: Path) -> tuple[str, list[str]]:
    exp = json.loads((fx / "expect.json").read_text(encoding="utf-8"))
    err = fx / "render_error.txt"
    report = (fx / "report.txt").read_text(encoding="utf-8") if (fx / "report.txt").exists() and not err.exists() else ""
    # the CHECKS header explains the DEFECT/note convention; match findings only
    report = "\n".join(l for l in report.splitlines() if not l.startswith("CHECKS"))
    problems = [f"missing: {s!r}" for s in exp.get("must", []) if s not in report]
    problems += [f"unexpected: {s!r}" for s in exp.get("must_not", []) if s in report]
    if err.exists():
        problems.insert(0, "render error: " + err.read_text(encoding="utf-8").splitlines()[0])
    gap = exp.get("known_gap", False)
    if problems:
        return ("XFAIL" if gap else "FAIL"), problems
    return ("XPASS" if gap else "PASS"), []


def main() -> None:
    fixtures = sorted(p for p in FIXTURES.iterdir() if (p / "expect.json").exists())
    for fx in fixtures:
        (fx / "report.txt").unlink(missing_ok=True)
    render.render_entries(fixtures)
    print()
    tally: dict[str, int] = {}
    for fx in fixtures:
        status, problems = check(fx)
        tally[status] = tally.get(status, 0) + 1
        why = json.loads((fx / "expect.json").read_text(encoding="utf-8")).get("why", "")
        print(f"{status:5}  {fx.name}" + (f"   ({why})" if status != "PASS" else ""))
        for p in problems:
            print(f"         {p}")
        if status == "XPASS":
            print("         gap looks fixed: set known_gap to false in expect.json")
    print("\n" + "  ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    sys.exit(1 if tally.get("FAIL") or tally.get("XPASS") else 0)


if __name__ == "__main__":
    main()
