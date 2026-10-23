"""Build the README media in docs/media/ (committed, unlike per-entry render outputs).

Usage:
    python tools/make_readme_media.py        # needs entries rendered first (tools/render.py --all)

Writes: banner.gif (docs/banner/anim.html, 1280x400), showcase GIFs re-encoded small,
and the example filmstrip / onion / alpha proof shown in the README.
"""
from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

BANK = render.BANK
OUT = BANK / "docs" / "media"
BANNER = BANK / "docs" / "banner"
SHOWCASE = ["bouncy-ball-squash", "punch-pow-badge", "coin-flip-land",
            "vs-split", "leaderboard-swap", "kinetic-three-words"]
VERTICAL = ["hook-title-slam", "top3-countdown"]
STILLS = {  # entry -> (source file, name in docs/media)
    "jelly-cube-hop": ("filmstrip.png", "filmstrip-jelly-cube-hop.png"),
    "bouncy-ball-squash": ("onion.png", "onion-bouncy-ball-squash.png"),
    "vs-split": ("alpha_check.png", "alpha-vs-split.png"),
}


def gif(src: Path, out: Path, width: int | None = None, height: int | None = None, fps: int = 25) -> None:
    scale = f"scale={width}:-2" if width else f"scale=-2:{height}"
    vf = (f"fps={fps},{scale}:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    render.ffmpeg(["-i", str(src), "-filter_complex", vf, "-loop", "0", str(out)], OUT)


def banner() -> None:
    srv, port = render.start_server()
    frames = BANNER / "_frames"
    try:
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir()
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 1280, "height": 400})
            page.goto(f"http://127.0.0.1:{port}/docs/banner/anim.html")
            page.wait_for_function("() => !!window.TL")
            dur = float(page.evaluate("() => window.TL.duration()"))
            for i in range(int(math.floor(dur * 30)) + 1):
                page.evaluate(f"() => {{ window.TL.pause().seek({i / 30}, false); }}")
                page.screenshot(path=str(frames / f"{i:04d}.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 400})
            b.close()
        vf = ("scale=1280:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
              "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        render.ffmpeg(["-framerate", "30", "-i", "%04d.png", "-filter_complex", vf, "-loop", "0",
                       str(OUT / "banner.gif")], frames)
    finally:
        srv.shutdown()
        shutil.rmtree(frames, ignore_errors=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    banner()
    for eid in SHOWCASE:
        gif(BANK / "entries" / eid / "preview.gif", OUT / f"{eid}.gif", width=400)
    for eid in VERTICAL:
        gif(BANK / "entries" / eid / "preview.gif", OUT / f"{eid}.gif", height=420)
    for eid, (src, name) in STILLS.items():
        shutil.copy(BANK / "entries" / eid / src, OUT / name)
    total = 0
    for f in sorted(OUT.iterdir()):
        total += f.stat().st_size
        print(f"{f.stat().st_size / 1024:8.0f} KB  {f.name}")
    print(f"{total / 1024 / 1024:8.1f} MB  total")


if __name__ == "__main__":
    main()
