"""Pick the k best bank examples for a request (status keep, not holdout).

Usage:
    python tools/retrieve.py "headline reveals letter by letter" [-k 3] [--vertical]

Score = 2 x tag overlap + keyword overlap with prompt.txt. No embeddings, easy to inspect.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent
ENTRIES = BANK / "entries"
STOP = set("""a an and the of to in on with for from by at as is it its into onto that this then than
up out off over under so very slightly softly smooth smoothly nice clean gently one each""".split())


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def load_pool(vertical: bool = False) -> list[dict]:
    pool = []
    for d in sorted(ENTRIES.iterdir()):
        mp, pp, ap = d / "meta.json", d / "prompt.txt", d / "anim.html"
        if not (mp.exists() and pp.exists() and ap.exists()):
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if meta.get("status") != "keep" or meta.get("holdout"):
            continue
        if ("vertical" in meta.get("tags", [])) != vertical:
            continue  # examples must match the requested format
        meta["id"] = meta.get("id") or d.name
        meta["prompt"] = pp.read_text(encoding="utf-8").strip()
        meta["dir"] = d
        pool.append(meta)
    return pool


def retrieve(request: str, k: int = 3, vertical: bool = False) -> list[dict]:
    req = tokens(request)
    scored = []
    for e in load_pool(vertical):
        if e["prompt"].strip().lower() == request.strip().lower():
            continue  # never hand the model the answer to the same prompt
        tag_tokens = set().union(*(tokens(t.replace("-", " ")) for t in e.get("tags", []))) if e.get("tags") else set()
        tag_hits = len(req & tag_tokens)
        kw_hits = len(req & tokens(e["prompt"]))
        e["score"] = 2 * tag_hits + kw_hits
        e["why"] = f"tags {sorted(req & tag_tokens)} words {sorted(req & tokens(e['prompt']))}"
        scored.append(e)
    scored.sort(key=lambda e: (-e["score"], e["id"]))
    return scored[:k]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--vertical", action="store_true", help="9:16 request: only vertical examples")
    args = ap.parse_args()
    hits = retrieve(args.request, args.k, args.vertical)
    if not hits:
        print("no keep entries outside holdout yet")
    for e in hits:
        print(f"{e['score']:>3}  {e['id']}  {e['prompt']}\n     {e['why']}")


if __name__ == "__main__":
    main()
