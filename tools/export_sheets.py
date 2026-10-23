"""Copy every entry's sprite sheet (filmstrip.png, 20 timestamped frames) into anim_bank/sprites/<id>.png
for sharing, e.g. dragging into Claude in the browser. --kind onion exports the motion-trail images instead.

Usage:
    python tools/export_sheets.py [--status keep|reject|pending] [--kind filmstrip|onion]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", choices=["keep", "reject", "pending"], help="only entries with this status")
    ap.add_argument("--kind", choices=["filmstrip", "onion"], default="filmstrip")
    args = ap.parse_args()
    OUT = BANK / ("sprites" if args.kind == "filmstrip" else "onions")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    n = 0
    for d in sorted((BANK / "entries").iterdir()):
        src, meta = d / f"{args.kind}.png", d / "meta.json"
        if not src.exists():
            continue
        if args.status and json.loads(meta.read_text(encoding="utf-8")).get("status") != args.status:
            continue
        shutil.copy(src, OUT / f"{d.name}.png")
        n += 1
    print(f"{n} {args.kind}s -> {OUT}")


if __name__ == "__main__":
    main()
