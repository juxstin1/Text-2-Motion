"""Render anim_bank entries deterministically and measure their motion.

Usage:
    python tools/render.py entries/<id>      # one entry
    python tools/render.py --all             # every entry with an anim.html
    python tools/render.py entries/<id> --alpha   # also export transparent 1080p alpha.webm + alpha.mov

Per entry writes: preview.gif, filmstrip.png, onion.png, motion.json, report.txt
(or render_error.txt if the page fails). Raw frames are deleted afterwards.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

BANK = Path(__file__).resolve().parent.parent
ENTRIES = BANK / "entries"
FPS = 30
W, H = 1280, 720          # landscape stage; vertical stages are H x W (720x1280)
SIZES = {(1280, 720): "landscape", (720, 1280): "vertical"}
GIF_LONG = 800
TILE_LONG, TILE_SHORT = 384, 216
# vertical safe zones (fractions of the stage) where Shorts/Reels/TikTok UI covers the video
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT, SAFE_RIGHT_FROM = 0.08, 0.80, 0.86, 0.40
STRIP_N = 20
LABEL_FONT = next((p for p in [Path("C:/Windows/Fonts/consola.ttf"), Path("C:/Windows/Fonts/arial.ttf")] if p.exists()), None)
FORBIDDEN_PROPS = {"top", "left", "right", "bottom", "width", "height", "margin", "marginTop", "marginLeft", "padding"}
FORBIDDEN_FONTS = {"arial", "helvetica", "times", "times new roman", "system-ui", "sans-serif", "serif"}

# ---------------------------------------------------------------- in-page JS

JS_SETUP = r"""
() => {
  const TL = window.TL;
  const st = document.getElementById('stage');
  const SKIP = new Set(['duration','ease','delay','stagger','repeat','yoyo','repeatDelay','yoyoEase',
    'onComplete','onStart','onUpdate','onRepeat','onReverseComplete','onInterrupt','onCompleteParams',
    'onUpdateParams','onStartParams','callbackScope','immediateRender','overwrite','id','paused','reversed',
    'startAt','runBackwards','keyframes','data','lazy','inherit','parent','defaults','autoRevert',
    'modifiers','snap','transformOrigin','svgOrigin','force3D','clearProps','smoothOrigin']);
  const els = [], labels = new Map(), groups = {};
  const track = el => {
    if (labels.has(el)) return labels.get(el);
    let l;
    if (el.id) l = '#' + el.id;
    else {
      let a = el.parentElement;
      while (a && !a.id) a = a.parentElement;
      const base = a && a !== st ? '#' + a.id + ' ' : '';
      const cls = ((el.getAttribute('class') || '').trim().split(/\s+/)[0]) || '';
      const key = base + el.tagName.toLowerCase() + (cls ? '.' + cls : '');
      groups[key] = (groups[key] || 0) + 1;
      l = key + '[' + (groups[key] - 1) + ']';
    }
    labels.set(el, l); els.push(el); return l;
  };
  const easeOf = tw => {
    let e = tw.vars.ease, p = tw.parent;
    while (e === undefined && p) { e = p.vars && p.vars.defaults && p.vars.defaults.ease; if (p === TL) break; p = p.parent; }
    if (e === undefined) return 'power1.out';
    return typeof e === 'function' ? 'custom' : String(e);
  };
  const propsOf = v => {
    const keys = new Set(Object.keys(v).filter(k => !SKIP.has(k)));
    const kf = v.keyframes;
    if (kf) (Array.isArray(kf) ? kf : [kf]).forEach(f => Object.keys(f).forEach(k => { if (!SKIP.has(k)) keys.add(k); }));
    return [...keys];
  };
  const tweens = TL.getChildren(true, true, false).map(tw => {
    let start = tw.startTime(), p = tw.parent;
    while (p && p !== TL) { start = p.startTime() + start / (p.timeScale() || 1); p = p.parent; }
    const targets = tw.targets();
    const tl = [];
    let objects = 0;
    targets.forEach(t => (t instanceof Element) ? tl.push(track(t)) : objects++);
    return {
      start: +start.toFixed(3), duration: +tw.totalDuration().toFixed(3), ease: easeOf(tw),
      props: propsOf(tw.vars), type: tw.vars.runBackwards ? 'from' : (tw.vars.startAt ? 'fromTo' : 'to'),
      stagger: tw.vars.stagger === undefined ? null : (typeof tw.vars.stagger === 'object' ? (tw.vars.stagger.each ?? tw.vars.stagger.amount ?? 'obj') : tw.vars.stagger),
      targets: tl, objects,
    };
  });
  // static text: track text-bearing elements the timeline never touches, so a moving element
  // landing on a still headline is caught (pairs of two static elements are layout, not checked)
  const nAnimated = els.length;
  (st || document.body).querySelectorAll('*').forEach(n => {
    if (labels.has(n)) return;
    const txt = /^(text|tspan)$/.test(n.tagName) ||
      [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
    if (txt && !n.closest('[data-layer="back"]') && n.getBoundingClientRect().width > 0) track(n);
  });
  const animated = els.map((e, i) => i < nAnimated);
  // single-member groups lose their [0] suffix
  const finalLabel = el => { const l = labels.get(el); const k = l.replace(/\[\d+\]$/, ''); return (k !== l && groups[k] === 1) ? k : l; };
  const rename = Object.fromEntries(els.map(e => [labels.get(e), finalLabel(e)]));
  tweens.forEach(t => t.targets = t.targets.map(l => rename[l]));
  // shapes inside one <svg> are one graphic, so they aren't checked against each other;
  // free-standing text (a headline placed straight in the svg) is still checked,
  // text inside a group with shapes (a coin's letter, a badge count) counts as part of the graphic
  const hasText = el => {
    if (!/^(text|tspan|textPath)$/.test(el.tagName)) return false;
    for (let g = el.parentElement; g && g !== el.ownerSVGElement; g = g.parentElement)
      if (g.tagName === 'g' && g.querySelector('path,circle,rect,ellipse,polygon,polyline,line')) return false;
    return true;
  };
  const related = [];
  for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++)
    if (els[i].contains(els[j]) || els[j].contains(els[i]) ||
        (els[i].ownerSVGElement && els[i].ownerSVGElement === els[j].ownerSVGElement &&
         !hasText(els[i]) && !hasText(els[j]))) related.push([i, j]);
  // data-layer="back": declared backing elements (panels, highlights, axis lines, rings) sit behind content.
  // Only the marked element is skipped, never its children (a plate's logos and text stay checked);
  // shapes inside a marked <svg> count as part of that one backing graphic.
  const isBack = e => {
    const m = e.closest('[data-layer="back"]');
    if (!m) return false;
    if (m === e) return true;
    const svg = e.ownerSVGElement;
    return !!svg && (m === svg || svg.contains(m));
  };
  const backdrop = els.map((e, i) => isBack(e) ? i : -1).filter(i => i >= 0);
  const isText = els.map(e => /^(text|tspan|textPath)$/.test(e.tagName) ||
    [...e.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()));
  // fonts actually used by text in the stage
  const fonts = new Set();
  (st || document.body).querySelectorAll('*').forEach(n => {
    if ([...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) fonts.add(getComputedStyle(n).fontFamily);
  });
  window.__MEL = els;
  return { duration: TL.duration(), tweens, labels: els.map(finalLabel), related, fonts: [...fonts], backdrop, isText, animated,
           stage: !!st, stageSize: st ? [st.offsetWidth, st.offsetHeight] : null };
}
"""

JS_BOXES = r"""
() => {
  const st = document.getElementById('stage');
  const sr = st ? st.getBoundingClientRect() : { left: 0, top: 0 };
  const r1 = v => Math.round(v * 10) / 10;
  // text elements: trim the box horizontally to the glyphs (full-width centred text boxes are mostly empty);
  // vertical extent stays the layout box, since glyph boxes of tightly leaded lines overlap
  const inkX = (el, r) => {
    if (![...el.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) return [r.left, r.right];
    const rg = document.createRange(); rg.selectNodeContents(el);
    const t = rg.getBoundingClientRect();
    return t.width ? [Math.max(r.left, t.left), Math.min(r.right, t.right)] : [r.left, r.right];
  };
  return window.__MEL.map(el => {
    const r = el.getBoundingClientRect();
    let [x0, x1] = inkX(el, r), y0 = r.top, y1 = r.bottom, o = 1, vis = true;
    if (/^(text|tspan|textPath)$/.test(el.tagName)) {
      // svg text boxes span the font's full em box; trim to roughly cap height so tight stacks don't read as overlap
      y0 += r.height * 0.22; y1 -= r.height * 0.2;
    }
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      o *= parseFloat(cs.opacity);
      if (cs.display === 'none') vis = false;
      if (n === el && cs.visibility === 'hidden') vis = false;
      if (n === st) break;
      if (n !== el && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible')) {
        const a = n.getBoundingClientRect();
        x0 = Math.max(x0, a.left); y0 = Math.max(y0, a.top); x1 = Math.min(x1, a.right); y1 = Math.min(y1, a.bottom);
      }
    }
    const cw = Math.max(0, x1 - x0), ch = Math.max(0, y1 - y0);
    return [r1(r.left - sr.left), r1(r.top - sr.top), r1(r.width), r1(r.height),
            r1(x0 - sr.left), r1(y0 - sr.top), r1(cw), r1(ch), vis ? Math.round(o * 1000) / 1000 : 0];
  });
}
"""

# ---------------------------------------------------------------- local server


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def start_server() -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = functools.partial(_Quiet, directory=str(BANK))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ---------------------------------------------------------------- analysis


def _ranges(frames: list[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return [(a, b) for a, b in out]


def _group(label: str) -> str:
    """'#title div[3]' -> '#title div' so per-character flags collapse into one line."""
    return label.rsplit("[", 1)[0] if label.endswith("]") else label


def analyse(setup: dict, boxes: np.ndarray, times: list[float], pixel_motion: list[bool], size: tuple[int, int]) -> dict:
    """boxes: [frames, elements, 9] = raw x,y,w,h, clipped x,y,w,h, opacity."""
    sw, sh = size
    labels = setup["labels"]
    backdrop = set(setup.get("backdrop", []))
    animated = setup.get("animated") or [True] * len(labels)
    is_text = setup["isText"]
    nf, ne = boxes.shape[0], boxes.shape[1]
    related = {tuple(p) for p in setup["related"]}
    visible = (boxes[:, :, 8] > 0.05) & (boxes[:, :, 6] > 0.5) & (boxes[:, :, 7] > 0.5)

    # (a) overlaps between unrelated visible elements, >10% of the smaller clipped area
    overlap_frames: dict[tuple[int, int], list[int]] = {}
    overlap_peak: dict[tuple[int, int], tuple[float, int]] = {}
    cx0, cy0 = boxes[:, :, 4], boxes[:, :, 5]
    cx1, cy1 = cx0 + boxes[:, :, 6], cy0 + boxes[:, :, 7]
    area = boxes[:, :, 6] * boxes[:, :, 7]
    for i in range(ne):
        for j in range(i + 1, ne):
            if (i, j) in related or i in backdrop or j in backdrop:
                continue
            if not (animated[i] or animated[j]):
                continue  # two static elements = layout, not motion
            both = visible[:, i] & visible[:, j]
            if not both.any():
                continue
            iw = np.clip(np.minimum(cx1[:, i], cx1[:, j]) - np.maximum(cx0[:, i], cx0[:, j]), 0, None)
            ih = np.clip(np.minimum(cy1[:, i], cy1[:, j]) - np.maximum(cy0[:, i], cy0[:, j]), 0, None)
            smaller = np.maximum(np.minimum(area[:, i], area[:, j]), 1)
            frac = np.where(both, iw * ih / smaller, 0)
            # one element fully inside a much larger one = intended layering (text on a card, art in a frame)
            larger = np.maximum(area[:, i], area[:, j])
            frac = np.where((frac > 0.98) & (larger >= 4 * smaller), 0, frac)
            hit = np.nonzero(frac > 0.10)[0]
            # single-frame contacts are noise; a collision has to persist for 2+ frames
            hit = np.array([f for a, b in _ranges(hit.tolist()) if b > a for f in range(a, b + 1)], dtype=int)
            if len(hit):
                overlap_frames[(i, j)] = hit.tolist()
                k = int(hit[np.argmax(frac[hit])])
                overlap_peak[(i, j)] = (float(frac[k]), k)

    # (b) off-stage while visible (raw rect clipped by inner masks, not by the stage)
    off_frames: dict[int, list[int]] = {}
    for i in range(ne):
        out = visible[:, i] & ((cx0[:, i] < -1) | (cy0[:, i] < -1) | (cx1[:, i] > sw + 1) | (cy1[:, i] > sh + 1))
        hit = np.nonzero(out)[0]
        if len(hit):
            off_frames[i] = hit.tolist()

    # (c) jumps: per-frame centre displacement > 3x the largest of its +-2 neighbours (and > 8px)
    centres = boxes[:, :, 0:2] + boxes[:, :, 2:4] / 2
    jumps: list[tuple[int, int, float]] = []
    if nf > 1:
        d = np.linalg.norm(np.diff(centres, axis=0), axis=2)  # [nf-1, ne]
        for i in range(ne):
            di = d[:, i]
            moving = di[di > 0.5]
            if len(moving) == 0:
                continue
            med = float(np.median(moving))
            for f in range(len(di)):
                if di[f] <= 8 or not (visible[f, i] or visible[f + 1, i]):
                    continue
                nb = np.concatenate([di[max(0, f - 2):f], di[f + 1:f + 3]])
                if di[f] > 3 * max(float(nb.max()) if len(nb) else 0.0, med):
                    jumps.append((i, f + 1, float(di[f])))

    # (d) dead air: runs > 0.4s with no box/opacity change and no pixel change, excluding the final hold
    box_motion = [False] + [bool(np.abs(boxes[f] - boxes[f - 1]).max() > 0.5) for f in range(1, nf)] if ne else [False] * nf
    moving_f = [b or p for b, p in zip(box_motion, pixel_motion)]
    still = [f for f in range(1, nf) if not moving_f[f]]
    dead = []
    last_motion = max((f for f in range(nf) if moving_f[f]), default=0)
    for a, b in _ranges(still):
        if b >= nf - 1 and a > last_motion:
            continue  # final hold
        if (b - a + 1) / FPS > 0.4:
            dead.append((a - 1, b))
    final_hold = (times[-1] - times[last_motion]) if nf else 0.0

    # (f) vertical safe zones: visible text under the platform UI (top bar, bottom caption area, right button column)
    unsafe: dict[int, list[int]] = {}
    if SIZES.get(size) == "vertical":
        for i in range(ne):
            if not setup["isText"][i]:
                continue
            zone = ((cy0[:, i] < sh * SAFE_TOP) | (cy1[:, i] > sh * SAFE_BOTTOM) |
                    ((cx1[:, i] > sw * SAFE_RIGHT) & (cy1[:, i] > sh * SAFE_RIGHT_FROM)))
            hit = np.nonzero(visible[:, i] & zone)[0]
            if len(hit) > 1:
                unsafe[i] = hit.tolist()

    # (e) end state
    end_vis = [i for i in range(ne) if visible[-1, i]] if nf else []
    end_overlaps = [(i, j) for (i, j), fr in overlap_frames.items() if fr[-1] == nf - 1]

    def longest(fr: list[int]) -> float:
        return max((b - a + 1) / FPS for a, b in _ranges(fr)) if fr else 0.0

    # DEFECT = wrong in the resting state, or text hidden long enough to lose a read; everything else is a note
    def overlap_defect(i: int, j: int, fr: list[int]) -> bool:
        return fr[-1] == nf - 1 or ((is_text[i] or is_text[j]) and longest(fr) >= 0.5)

    return {
        "overlaps": [
            {"a": labels[i], "b": labels[j], "ranges": [(times[x], times[y]) for x, y in _ranges(fr)],
             "peak": round(overlap_peak[(i, j)][0], 2), "peak_frame": overlap_peak[(i, j)][1], "ia": i, "ib": j,
             "defect": overlap_defect(i, j, fr),
             "static": not (animated[i] and animated[j])}
            for (i, j), fr in overlap_frames.items()
        ],
        # off-stage only matters once the motion has settled: entrances and exits through the edge are notes
        "offstage": [{"el": labels[i], "ranges": [(times[x], times[y]) for x, y in _ranges(fr)], "i": i,
                      "frame": fr[len(fr) // 2], "defect": fr[-1] == nf - 1} for i, fr in off_frames.items()],
        "jumps": [{"el": labels[i], "t": times[f], "px": round(px, 1)} for i, f, px in jumps],
        "dead_air": [(times[a], times[b]) for a, b in dead],
        "unsafe": [{"el": labels[i], "ranges": [(times[x], times[y]) for x, y in _ranges(fr)], "i": i,
                    "frame": fr[len(fr) // 2], "defect": fr[-1] == nf - 1 or longest(fr) >= 0.5}
                   for i, fr in unsafe.items()],
        "backdrop": len(backdrop),
        "format": SIZES.get(size, "other"),
        "final_hold": round(final_hold, 2),
        "end_visible": [labels[i] for i in end_vis],
        "end_overlaps": [(labels[i], labels[j]) for i, j in end_overlaps],
    }


def _collapse(items: list[str], limit: int) -> list[str]:
    if len(items) <= limit:
        return items
    return items[:limit] + [f"  (+{len(items) - limit} more)"]


def _fmt_ranges(rs) -> str:
    return ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in rs[:3]) + (" ..." if len(rs) > 3 else "")


def _group_counts(labels: list[str]) -> list[str]:
    out: dict[str, int] = {}
    for l in labels:
        out[_group(l)] = out.get(_group(l), 0) + 1
    return [k + (f" x{n}" if n > 1 else "") for k, n in out.items()]


def write_report(entry: Path, setup: dict, a: dict, warnings: list[str], nframes: int) -> bool:
    """Writes report.txt; returns True if anything was flagged."""
    tw = setup["tweens"]
    lines = [f"duration {setup['duration']:.2f}s, {nframes} frames @{FPS}fps, {len(tw)} tweens"]
    lines.append("TIMING")
    chart = []
    for t in sorted(tw, key=lambda t: t["start"]):
        if not t["targets"] and not t["props"]:
            chart.append(f"  (hold)  {t['start']:.2f}-{t['start'] + t['duration']:.2f}s")
            continue
        tgt = _group_counts(t["targets"]) or ([f"{{object}} x{t['objects']}"] if t["objects"] else ["?"])
        tgt_s = ", ".join(tgt[:2]) + (" ..." if len(tgt) > 2 else "")
        if t["duration"] == 0:
            chart.append(f"  {', '.join(tgt[:2])}  {','.join(t['props'])}  set at {t['start']:.2f}s")
            continue
        stag = f"  stagger {t['stagger']}" if t["stagger"] is not None else ""
        chart.append(f"  {tgt_s}  {','.join(t['props'])}  {t['start']:.2f}-{t['start'] + t['duration']:.2f}s  {t['ease']}{stag}")
    lines += _collapse(chart, 10)

    flagged = False
    lines.append("CHECKS  (fix every DEFECT; 'note' = mid-animation fact, change it only if unintended)")
    # contract
    contract = []
    if setup["duration"] > 4.0 + 1e-6:
        contract.append(f"duration {setup['duration']:.2f}s > 4s")
    bad_props = sorted({p for t in tw for p in t["props"] if p in FORBIDDEN_PROPS})
    if bad_props:
        contract.append("animates layout props " + ",".join(bad_props) + " (use x/y/scale)")
    lin = [t for t in tw if t["ease"] in ("none", "linear", "power0") and t["targets"]]
    if lin:
        contract.append(f"{len(lin)} tween(s) with linear ease")
    bad_fonts = sorted({f for f in setup["fonts"] if f.split(",")[0].strip().strip("'\"").lower() in FORBIDDEN_FONTS})
    if bad_fonts:
        contract.append("generic font " + "; ".join(bad_fonts))
    if not setup["stage"]:
        contract.append("no #stage element")
    elif tuple(setup["stageSize"]) not in SIZES:
        contract.append(f"#stage is {setup['stageSize']}, expected [1280, 720] or vertical [720, 1280]")
    contract += warnings
    lines.append("contract: " + ("DEFECT " + "; ".join(contract) if contract else "clean"))
    flagged |= bool(contract)

    def split(items: list[dict]) -> tuple[list[dict], list[dict]]:
        return [x for x in items if x["defect"]], [x for x in items if not x["defect"]]

    def head(name: str, d: list, n: list, extra: str = "") -> str:
        parts = ([f"{len(d)} DEFECT"] if d else []) + ([f"{len(n)} note"] if n else [])
        return f"{name}: " + (", ".join(parts) if parts else "clean") + extra

    od, on = split(a["overlaps"])
    fmt_o = lambda tag, o: (f"  {tag} {o['a']} / {o['b']}  {_fmt_ranges(o['ranges'])}  peak {int(o['peak'] * 100)}%"
                            + ("  (onto static text)" if o.get("static") else ""))
    back = f" ({a['backdrop']} data-layer=back excluded)" if a["backdrop"] else ""
    lines.append(head("overlap", od, on, back))
    lines += _collapse([fmt_o("DEFECT", o) for o in od], 4) + _collapse([fmt_o("note", o) for o in on], 2)
    fd, fn = split(a["offstage"])
    lines.append(head("off-stage", fd, fn))
    lines += _collapse([f"  DEFECT {o['el']} still off-stage at the end" for o in fd], 3)
    lines += _collapse([f"  note {o['el']}  {_fmt_ranges(o['ranges'])} (passes the edge)" for o in fn], 2)
    jm = [f"  DEFECT {j['el']}  at {j['t']:.2f}s  {j['px']}px in one frame" for j in a["jumps"]]
    lines.append("jumps: " + ("clean" if not jm else f"{len(jm)} DEFECT"))
    lines += _collapse(jm, 3)
    lines.append("dead air: " + ("clean" if not a["dead_air"] else "DEFECT " + _fmt_ranges(a["dead_air"])))
    ud, un = split(a["unsafe"])
    us = ud + un
    if a["format"] == "vertical":
        lines.append(head("safe zones", ud, un, " (text must stay out of top 8%, bottom 20%, right 14% below 40%)" if us else ""))
        lines += _collapse([f"  DEFECT {u['el']}  {_fmt_ranges(u['ranges'])}" for u in ud], 3)
        lines += _collapse([f"  note {u['el']}  {_fmt_ranges(u['ranges'])} (passes through)" for u in un], 2)
    end = _group_counts(a["end_visible"])
    lines.append(f"end state: {len(a['end_visible'])} visible ({', '.join(end[:4])}{' ...' if len(end) > 4 else ''}); "
                 f"final hold {a['final_hold']:.2f}s; "
                 + ("overlapping at end: " + ", ".join(f"{x}/{y}" for x, y in a["end_overlaps"][:2]) if a["end_overlaps"] else "no overlaps"))
    flagged |= bool(od or fd or jm or a["dead_air"] or ud)
    a["n_notes"] = len(on) + len(fn) + len(un)
    (entry / "report.txt").write_text("\n".join(lines[:30]) + "\n", encoding="utf-8")
    return flagged


# ---------------------------------------------------------------- images


def ffmpeg(args: list[str], cwd: Path) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + r.stderr.strip()[-800:])


def make_gif(frames_dir: Path, out: Path, vertical: bool = False) -> None:
    vf = (f"scale={'-2:' + str(GIF_LONG) if vertical else str(GIF_LONG) + ':-2'}:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    ffmpeg(["-framerate", str(FPS), "-i", "%04d.png", "-filter_complex", vf, "-loop", "0", str(out)], frames_dir)


def make_filmstrip(frames_dir: Path, times: list[float], out: Path, vertical: bool = False) -> None:
    # landscape: 5x4 tiles of 384x216; vertical: 10x2 tiles of 216x384 (same 20 frames, readable portrait tiles)
    tw, th, grid = (TILE_SHORT, TILE_LONG, "10x2") if vertical else (TILE_LONG, TILE_SHORT, "5x4")
    n = len(times)
    picks = sorted({round(i * (n - 1) / (STRIP_N - 1)) for i in range(STRIP_N)})
    while len(picks) < STRIP_N:  # very short animations: repeat the last frame
        picks.append(picks[-1])
    font = ""
    if LABEL_FONT:
        shutil.copy(LABEL_FONT, frames_dir / "label.ttf")
        font = "fontfile=label.ttf:"
    args, chains = [], []
    for k, f in enumerate(picks):
        args += ["-i", f"{f:04d}.png"]
        chains.append(f"[{k}:v]scale={tw}:{th}:flags=lanczos,drawtext={font}text='{times[f]:.2f}s':"
                      f"x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=5[v{k}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{k}]" for k in range(len(picks))) + \
        f"concat=n={len(picks)}:v=1:a=0,tile={grid}:padding=4:color=0x808080[out]"
    ffmpeg([*args, "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", str(out)], frames_dir)


def make_onion(frames: list[Path], boxes: np.ndarray, a: dict, out: Path) -> None:
    first = np.asarray(Image.open(frames[0]).convert("RGB"), dtype=np.float32)
    # background = the most common colour in the first frame
    flat = first.reshape(-1, 3)[::97].astype(np.int32)
    keys, counts = np.unique(flat[:, 0] * 65536 + flat[:, 1] * 256 + flat[:, 2], return_counts=True)
    k = int(keys[np.argmax(counts)])
    bg = np.array([k >> 16, (k >> 8) & 255, k & 255], dtype=np.float32)
    canvas = np.broadcast_to(bg, first.shape).copy()
    ghosts = frames[::3]
    if frames[-1] not in ghosts:
        ghosts.append(frames[-1])
    m = len(ghosts)
    for idx, fp in enumerate(ghosts):
        img = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32)
        mask = (np.abs(img - bg).max(axis=2) > 10)[:, :, None]
        alpha = 0.9 if idx == m - 1 else 0.10 + 0.45 * idx / max(1, m - 1)
        canvas = np.where(mask, canvas * (1 - alpha) + img * alpha, canvas)
    im = Image.fromarray(canvas.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    marks: list[tuple[int, int, str]] = []  # (element index, frame, note)
    for o in a["overlaps"]:
        if o["defect"]:
            marks += [(o["ia"], o["peak_frame"], "overlap"), (o["ib"], o["peak_frame"], "overlap")]
    for o in a["offstage"]:
        if o["defect"]:
            marks.append((o["i"], o["frame"], "off-stage"))
    for o in a.get("unsafe", []):
        if o["defect"]:
            marks.append((o["i"], o["frame"], "unsafe"))
    seen = set()
    for i, f, note in marks[:40]:
        if (i, f) in seen:
            continue
        seen.add((i, f))
        x, y, w, h = boxes[f, i, 0:4]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(im.width - 1, x + w), min(im.height - 1, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=3)
        draw.text((x0 + 4, max(0, y0 - 12)), note, fill=(255, 0, 0))
    im.save(out)


# ---------------------------------------------------------------- render


def render_entry(browser, port: int, entry: Path) -> str:
    entry = entry.resolve()
    for stale in ("render_error.txt",):
        (entry / stale).unlink(missing_ok=True)
    errors: list[str] = []
    warnings: list[str] = []
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    page.set_default_timeout(20000)
    page.on("pageerror", lambda e: errors.append(f"JS error: {e}"))
    page.on("console", lambda m: errors.append(f"console.error: {m.text}")
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: warnings.append(f"HTTP {r.status} {r.url.split(str(port), 1)[-1]}") if r.status >= 400 else None)
    frames_dir = entry / "_frames"
    try:
        rel = entry.resolve().relative_to(BANK).as_posix()
        page.goto(f"http://127.0.0.1:{port}/{rel}/anim.html", wait_until="load", timeout=15000)
        try:
            page.wait_for_function("() => window.TL && typeof window.TL.duration === 'function'", timeout=8000)
        except Exception:
            raise RuntimeError("\n".join(errors + ["window.TL missing after 8s (timeline must be assigned to window.TL)"]))
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.evaluate("() => { window.TL.pause(0); }")
        if errors:
            raise RuntimeError("\n".join(errors))
        setup = page.evaluate(JS_SETUP)
        size = tuple(setup["stageSize"]) if setup["stage"] and tuple(setup["stageSize"]) in SIZES else (W, H)
        vertical = SIZES.get(size) == "vertical"
        if size != (W, H):
            page.set_viewport_size({"width": size[0], "height": size[1]})
        dur = float(setup["duration"])
        if dur <= 0:
            raise RuntimeError("TL.duration() is 0; the timeline has no tweens")
        nframes = int(math.floor(dur * FPS + 1e-6)) + 1
        times = [min(i / FPS, dur) for i in range(nframes)]
        if times[-1] < dur - 1e-6:
            times.append(dur)
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        frames_dir.mkdir()
        clip = page.evaluate("""() => { const s = document.getElementById('stage');
            if (!s) return null; const r = s.getBoundingClientRect(); return {x: r.left, y: r.top}; }""")
        clip = {"x": clip["x"] if clip else 0, "y": clip["y"] if clip else 0, "width": size[0], "height": size[1]}
        all_boxes, frame_paths, pixel_motion = [], [], []
        prev_small = None
        for i, t in enumerate(times):
            page.evaluate(f"() => {{ window.TL.pause().seek({t}, false); }}")
            fp = frames_dir / f"{i:04d}.png"
            page.screenshot(path=str(fp), clip=clip, animations="disabled")
            frame_paths.append(fp)
            all_boxes.append(page.evaluate(JS_BOXES))
            small = np.asarray(Image.open(fp).convert("L").resize((320, 180)), dtype=np.int16)
            pixel_motion.append(prev_small is not None and int(np.abs(small - prev_small).max()) > 6)
            prev_small = small
        if errors:
            raise RuntimeError("\n".join(errors))
        boxes = np.array(all_boxes, dtype=np.float64).reshape(len(times), len(setup["labels"]), 9)
        a = analyse(setup, boxes, times, pixel_motion, size)
        flagged = write_report(entry, setup, a, sorted(set(warnings)), len(times))
        make_gif(frames_dir, entry / "preview.gif", vertical)
        make_filmstrip(frames_dir, times, entry / "filmstrip.png", vertical)
        make_onion(frame_paths, boxes, a, entry / "onion.png")
        motion = {"duration": dur, "fps": FPS, "frames": len(times), "format": SIZES.get(size), "size": size,
                  "tweens": setup["tweens"],
                  "elements": setup["labels"], "fonts": setup["fonts"], "flagged": flagged, "notes": a["n_notes"],
                  "checks": {k: v for k, v in a.items()}}
        (entry / "motion.json").write_text(json.dumps(motion, indent=1, default=float), encoding="utf-8")
        return f"ok    {entry.name}  {dur:.2f}s  {len(times)}f  {'vertical  ' if vertical else ''}{'DEFECTS' if flagged else ('notes' if a['n_notes'] else 'clean')}"
    except Exception as e:
        (entry / "render_error.txt").write_text(str(e) + "\n", encoding="utf-8")
        return f"ERROR {entry.name}  {str(e).splitlines()[0][:120]}"
    finally:
        page.close()
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)


ALPHA_CSS = "html, body, #stage { background: transparent !important; } #bg, [data-bg] { visibility: hidden !important; }"


def render_alpha(browser, port: int, entry: Path, scale: float) -> str:
    """Overlay export: background hidden (#bg / [data-bg], body, #stage), rendered at stage size * scale
    (1.5 -> 1920x1080 landscape, 1080x1920 vertical).
    Writes alpha.webm (VP9 + alpha, for web/CapCut), alpha.mov (ProRes 4444, for Premiere/DaVinci)
    and alpha_check.png (mid and end frames on a checkerboard, to verify transparency)."""
    entry = entry.resolve()
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=scale)
    page.set_default_timeout(20000)
    frames_dir = entry / "_alpha_frames"
    try:
        rel = entry.relative_to(BANK).as_posix()
        page.goto(f"http://127.0.0.1:{port}/{rel}/anim.html", wait_until="load", timeout=15000)
        page.wait_for_function("() => window.TL && typeof window.TL.duration === 'function'", timeout=8000)
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.add_style_tag(content=ALPHA_CSS)
        size = tuple(page.evaluate("() => { const s = document.getElementById('stage'); return s ? [s.offsetWidth, s.offsetHeight] : [1280, 720]; }"))
        if size != (W, H):
            page.set_viewport_size({"width": size[0], "height": size[1]})
        dur = float(page.evaluate("() => window.TL.duration()"))
        n = int(math.floor(dur * FPS + 1e-6)) + 1
        times = [min(i / FPS, dur) for i in range(n)] + ([dur] if (n - 1) / FPS < dur - 1e-6 else [])
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        frames_dir.mkdir()
        clip = page.evaluate("""() => { const s = document.getElementById('stage');
            if (!s) return {x: 0, y: 0}; const r = s.getBoundingClientRect(); return {x: r.left, y: r.top}; }""")
        clip = {"x": clip["x"], "y": clip["y"], "width": size[0], "height": size[1]}
        for i, t in enumerate(times):
            page.evaluate(f"() => {{ window.TL.pause().seek({t}, false); }}")
            page.screenshot(path=str(frames_dir / f"{i:04d}.png"), clip=clip, omit_background=True, animations="disabled")
        ffmpeg(["-framerate", str(FPS), "-i", "%04d.png", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-b:v", "0", "-crf", "18", "-auto-alt-ref", "0", str(entry / "alpha.webm")], frames_dir)
        ffmpeg(["-framerate", str(FPS), "-i", "%04d.png", "-c:v", "prores_ks", "-profile:v", "4444",
                "-pix_fmt", "yuva444p10le", "-vendor", "apl0", str(entry / "alpha.mov")], frames_dir)
        # checkerboard proof: mid frame | end frame
        tiles = []
        for f in (len(times) // 2, len(times) - 1):
            fg = Image.open(frames_dir / f"{f:04d}.png").convert("RGBA")
            w, h = fg.size
            yy, xx = np.mgrid[0:h, 0:w]
            board = np.where(((xx // 24 + yy // 24) % 2)[..., None] == 0, 204, 153).astype(np.uint8)
            bg = Image.fromarray(np.repeat(board, 3, axis=2)).convert("RGBA")
            tiles.append(Image.alpha_composite(bg, fg).convert("RGB").resize((w // 2, h // 2)))
        sheet = Image.new("RGB", (tiles[0].width * 2 + 8, tiles[0].height), (60, 60, 60))
        sheet.paste(tiles[0], (0, 0)); sheet.paste(tiles[1], (tiles[0].width + 8, 0))
        sheet.save(entry / "alpha_check.png")
        corner = np.asarray(Image.open(frames_dir / f"{len(times) - 1:04d}.png").convert("RGBA"))[..., 3]
        opaque = float((corner > 0).mean())
        return f"alpha {entry.name}  {int(size[0] * scale)}x{int(size[1] * scale)}  {len(times)}f  {opaque:.0%} of end frame opaque"
    except Exception as e:
        return f"ERROR alpha {entry.name}  {str(e).splitlines()[0][:120]}"
    finally:
        page.close()
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)


def render_entries(entries: list[Path], alpha: bool = False, scale: float = 1.5) -> list[str]:
    srv, port = start_server()
    out = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--font-render-hinting=none", "--disable-lcd-text"])
            for e in entries:
                line = render_entry(browser, port, e)
                print(line, flush=True)
                out.append(line)
                if alpha and not line.startswith("ERROR"):
                    print(render_alpha(browser, port, e, scale), flush=True)
            browser.close()
    finally:
        srv.shutdown()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entry", nargs="?", help="entry folder (e.g. entries/my-anim)")
    ap.add_argument("--all", action="store_true", help="render every entry")
    ap.add_argument("--alpha", action="store_true", help="also export transparent alpha.webm + alpha.mov")
    ap.add_argument("--scale", type=float, default=1.5, help="alpha export scale (1.5 = 1920x1080)")
    args = ap.parse_args()
    if args.all:
        entries = sorted(p.parent for p in ENTRIES.glob("*/anim.html"))
    elif args.entry:
        e = Path(args.entry)
        if not e.is_absolute() and not e.exists():
            e = ENTRIES / args.entry
        if not (e / "anim.html").exists():
            sys.exit(f"no anim.html in {e}")
        entries = [e]
    else:
        ap.error("give an entry folder or --all")
    if not entries:
        sys.exit("no entries found")
    lines = render_entries(entries, args.alpha, args.scale)
    bad = sum(l.startswith("ERROR") for l in lines)
    if len(lines) > 1:
        print(f"{len(lines) - bad}/{len(lines)} rendered, {bad} error(s)")


if __name__ == "__main__":
    main()
