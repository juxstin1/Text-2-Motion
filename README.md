# Text-2-Motion

A local bank of hand-picked GSAP animations, used as in-prompt examples (and later fine-tuning data) for a small local model. Rules for every animation: [CONTRACT.md](CONTRACT.md).

Setup (once): Python 3.11+, ffmpeg on PATH, then

```
pip install playwright numpy pillow
python -m playwright install chromium
```

GSAP 3.15.0 (+ SplitText, CustomEase, DrawSVGPlugin, MotionPathPlugin), 12 fonts and `style_packs.json` are already vendored in `vendor/`, so everything runs offline.

## Commands

Run from `anim_bank/`.

| command | what it does |
| --- | --- |
| `python tools/render.py entries/hero-title` | Render one entry: preview.gif, filmstrip.png (5x4, timestamped), onion.png (motion trails, red = flagged), motion.json, report.txt |
| `python tools/render.py entries/vs-split --alpha` | Also export a transparent 1920x1080 overlay: alpha.mov (ProRes 4444, Premiere/DaVinci), alpha.webm (VP9 alpha, web/CapCut), alpha_check.png (checkerboard proof). `--scale 1` for 720p |
| `python tools/render.py --all` | Render every entry. Failures write `render_error.txt` and the run continues |
| `python tools/gallery.py` | Open the review gallery at http://127.0.0.1:8765/. K keep, R reject, H holdout, T tags, ←/→ navigate. Compare: `http://127.0.0.1:8765/?a=<id>&b=<id>` |
| `python tools/retrieve.py "headline reveals letter by letter" -k 3` | Show the 3 best keep examples (holdouts excluded) and why they matched |
| `python tools/run_local.py "pricing card slides up" --shots 3` | Ask LM Studio (localhost:1234) for an animation with 3 bank examples, save it as a pending entry, render it |
| `python tools/run_local.py "pricing card slides up" --shots 0 --fix 2 --vision` | Same with 0 examples, then up to 2 repair rounds fed by report.txt (+ filmstrip/onion images for vision models). Each attempt is its own entry |

`python tools/export_sheets.py [--status keep]` copies every sprite sheet (filmstrip.png) to `sprites/<id>.png` for sharing; `--kind onion` exports onions instead.

Vertical (9:16): stage 720x1280 plus `<!-- format: vertical -->`; the renderer adapts (portrait filmstrip, 1080x1920 alpha) and checks platform safe zones. `retrieve.py --vertical` / `run_local.py --vertical` use only vertical examples.

`run_local.py` options: `--model NAME` (default: first loaded model), `--url`, `--temperature 0.4`, `--max-tokens 12000`.

## Entry layout

`entries/<id>/`: `anim.html`, `prompt.txt`, `meta.json` (id, prompt, tags, source, status pending|keep|reject, holdout, created), plus the render outputs. Local-model entries also keep `raw_reply.txt` and record `shots`, `examples`, `attempt`, `parent` in meta.json.

## Reading report.txt

A timing chart (one line per tween), then the checks. Each finding is either a **DEFECT** (fix it) or a **note** (a mid-animation fact; change it only if unintended). `run_local.py --fix` only acts on defects.

- **contract** (DEFECT): over 4s, layout props, linear ease, generic fonts, wrong stage size.
- **overlap**: animated elements plus static text are checked. Ignored: ancestor/child pairs, non-text shapes in one `<svg>`, small elements fully inside a 4x-larger one, contacts under 2 frames, `data-layer="back"` elements, static/static pairs. DEFECT if still overlapping at the end, or text covered for 0.5s+; otherwise a note.
- **off-stage**: DEFECT only if still off-stage at the end; passing through the edge is a note.
- **jumps** (DEFECT): one-frame moves over 3x the surrounding motion.
- **dead air** (DEFECT): over 0.4s with nothing moving, final hold excluded.
- **safe zones** (vertical only): text under platform UI; DEFECT at the end or for 0.5s+.
- **end state**: what's visible, the final hold length, and any end overlaps.

Text boxes are trimmed horizontally to their glyphs, SVG text vertically to cap height.
