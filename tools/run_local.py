"""Ask a local OpenAI-compatible model (LM Studio by default) for an animation, save and render it.

Usage:
    python tools/run_local.py "<request>" [--shots 0|3] [--model NAME] [--fix N] [--vision]
           [--vertical] [--url http://localhost:1234/v1] [--temperature 0.4] [--max-tokens 12000]

Each attempt (initial + every --fix round) is saved as its own entry with status pending.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402
from retrieve import retrieve  # noqa: E402

BANK = render.BANK
ENTRIES = render.ENTRIES
INSTRUCTION = "Return only the full anim.html in one ```html block."


def http_json(url: str, payload: dict | None = None, timeout: float = 900) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def pick_model(base: str, wanted: str | None) -> str:
    try:
        models = [m["id"] for m in http_json(f"{base}/models", timeout=5).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit(f"No local model server answered at {base} ({e}).\n"
                 "Start LM Studio, load a model, and enable the server (Developer tab -> Start Server), "
                 "or pass --url.")
    if wanted:
        return wanted
    if not models:
        sys.exit(f"Server at {base} is up but has no model loaded. Load one or pass --model.")
    return models[0]


def chat(base: str, model: str, messages: list[dict], temperature: float, max_tokens: int) -> str:
    t0 = time.time()
    resp = http_json(f"{base}/chat/completions", {
        "model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False,
    })
    text = resp["choices"][0]["message"].get("content") or ""
    usage = resp.get("usage", {})
    print(f"  model replied in {time.time() - t0:.0f}s  (prompt {usage.get('prompt_tokens', '?')} tok, "
          f"completion {usage.get('completion_tokens', '?')} tok)")
    return text


def extract_html(text: str) -> str | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    blocks = re.findall(r"```(?:html|HTML)?\s*\n(.*?)```", text, re.S)
    blocks = [b for b in blocks if "<html" in b.lower() or "<!doctype" in b.lower()] or blocks
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    if "<html" in text.lower():  # unfenced answer
        return text[text.lower().find("<!doctype") if "<!doctype" in text.lower() else text.lower().find("<html"):].strip() + "\n"
    return None


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def save_entry(request: str, html: str | None, raw: str, model: str, extra: dict) -> Path:
    stamp = time.strftime("%m%d-%H%M%S")
    eid = f"{slug(request)}--{slug(model, 20)}-{extra['shots']}s-{stamp}" + (f"-fix{extra['attempt']}" if extra.get("attempt") else "")
    d = ENTRIES / eid
    d.mkdir(parents=True)
    (d / "prompt.txt").write_text(request + "\n", encoding="utf-8")
    (d / "raw_reply.txt").write_text(raw, encoding="utf-8")
    if html:
        (d / "anim.html").write_text(html, encoding="utf-8")
    tags = ["local", f"{extra['shots']}-shot"] + (["vertical"] if "vertical 9:16" in request else [])
    meta = {"id": eid, "prompt": request, "tags": tags, "source": model,
            "status": "pending", "holdout": False, "created": date.today().isoformat(), **extra}
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    return d


def needs_fix(d: Path) -> str | None:
    """Returns the feedback text if the render errored or the report flagged something."""
    if (d / "render_error.txt").exists():
        return "The page failed to render:\n" + (d / "render_error.txt").read_text(encoding="utf-8")
    mj = d / "motion.json"
    if mj.exists() and json.loads(mj.read_text(encoding="utf-8")).get("flagged"):
        return "Measured motion report from the renderer:\n" + (d / "report.txt").read_text(encoding="utf-8")
    return None


def image_part(p: Path) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request")
    ap.add_argument("--shots", type=int, choices=[0, 3], default=0)
    ap.add_argument("--model", help="model id (default: first model the server lists)")
    ap.add_argument("--url", default="http://localhost:1234/v1")
    ap.add_argument("--fix", type=int, default=0, help="max repair rounds driven by report.txt")
    ap.add_argument("--vision", action="store_true", help="attach filmstrip.png + onion.png to fix requests")
    ap.add_argument("--vertical", action="store_true", help="9:16 Shorts format (720x1280 stage, vertical examples)")
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument("--max-tokens", type=int, default=12000)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    model = pick_model(base, args.model)
    system = (BANK / "CONTRACT.md").read_text(encoding="utf-8") + "\n\n" + INSTRUCTION
    messages = [{"role": "system", "content": system}]
    examples = []
    if args.shots:
        examples = retrieve(args.request, args.shots, args.vertical)
        if len(examples) < args.shots:
            print(f"warning: only {len(examples)} keep examples available (wanted {args.shots})")
        for e in examples:
            messages += [{"role": "user", "content": e["prompt"]},
                         {"role": "assistant", "content": "```html\n" + (e["dir"] / "anim.html").read_text(encoding="utf-8").strip() + "\n```"}]
        print("examples:", ", ".join(e["id"] for e in examples) or "none")
    if args.vertical:
        args.request += " (vertical 9:16 format: 720x1280 stage, follow the Vertical format rules)"
    messages.append({"role": "user", "content": args.request})

    print(f"asking {model} ({args.shots}-shot) ...")
    raw = chat(base, model, messages, args.temperature, args.max_tokens)
    html = extract_html(raw)
    extra = {"shots": args.shots, "examples": [e["id"] for e in examples], "attempt": 0}
    d = save_entry(args.request, html, raw, model, extra)
    if html:
        render.render_entries([d])
    else:
        (d / "render_error.txt").write_text("no ```html block in the model reply (see raw_reply.txt)\n", encoding="utf-8")
        print(f"ERROR {d.name}  no html block in reply")

    for n in range(1, args.fix + 1):
        feedback = needs_fix(d)
        if not feedback or not (d / "anim.html").exists():
            break
        prev_html = (d / "anim.html").read_text(encoding="utf-8")
        text = (f"Here is your anim.html for the request above:\n```html\n{prev_html.strip()}\n```\n\n{feedback}\n"
                "Fix every flagged issue (lines that do not say 'clean') while keeping the design and intent. "
                + INSTRUCTION)
        content: list[dict] | str = text
        if args.vision:
            imgs = [p for p in (d / "filmstrip.png", d / "onion.png") if p.exists()]
            if imgs:
                content = [{"type": "text", "text": text + "\nAttached: filmstrip.png (20 frames with timestamps) and "
                                                         "onion.png (motion trails; red boxes mark flagged elements)."}]
                content += [image_part(p) for p in imgs]
        fix_msgs = [{"role": "system", "content": system}, {"role": "user", "content": args.request},
                    {"role": "assistant", "content": "```html\n" + prev_html.strip() + "\n```"},
                    {"role": "user", "content": content}]
        print(f"fix round {n} ...")
        raw = chat(base, model, fix_msgs, args.temperature, args.max_tokens)
        html = extract_html(raw)
        d = save_entry(args.request, html, raw, model, {**extra, "attempt": n, "parent": d.name})
        if not html:
            (d / "render_error.txt").write_text("no ```html block in the model reply (see raw_reply.txt)\n", encoding="utf-8")
            print(f"ERROR {d.name}  no html block in reply")
            break
        render.render_entries([d])
    final = needs_fix(d)
    print(f"done: {d.name}  ({'still flagged' if final else 'clean'})")


if __name__ == "__main__":
    main()
