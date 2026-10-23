# Animation Contract

Every animation in this bank follows these rules. The renderer, gallery and local-model runner all depend on them.

## File
- One self-contained file `anim.html` per animation, in `entries/<id>/`.
- First line inside `<head>` is a comment naming the style pack: `<!-- pack: editorial -->`.
- No external images and no network requests. Inline SVG only.

## Stage
- `body { margin: 0; background: <pack background>; }`
- One stage element: `<div id="stage">`, 1280x720, `position: relative; overflow: hidden;`, background set explicitly.
- Every animated element lives inside `#stage`.

## GSAP
- Load GSAP from `../../vendor/gsap.min.js`.
- Plugins vendored from the same free GSAP 3.15.0 package (load only what you use, after gsap.min.js, then `gsap.registerPlugin(...)`):
  - `../../vendor/SplitText.min.js` (split text into chars/words/lines)
  - `../../vendor/CustomEase.min.js`
  - `../../vendor/DrawSVGPlugin.min.js` (stroke drawing on SVG paths)
  - `../../vendor/MotionPathPlugin.min.js` (move elements along a curve: `motionPath: { path: "#curve", align: "#curve", autoRotate: true }`)
- Build exactly one timeline, created paused, assigned to `window.TL`:
  `window.TL = gsap.timeline({ paused: true });`
- Total duration 4 seconds or less, including a short final hold.
- Build the timeline only after fonts load (SplitText needs final metrics):
  `document.fonts.ready.then(() => { /* build window.TL here */ });`
- Animate transform and opacity only: `x, y, xPercent, yPercent, scale, scaleX, scaleY, rotation, skewX, autoAlpha`. Never `top, left, width, height, margin`, which cause layout jank. SVG `drawSVG` and `fill`/`color` tweens are allowed.
- Never use linear (`"none"`) easing for motion. Pick a deliberate ease: `power2-4`, `expo`, `back` (overshoot), `elastic` (sparingly).
- Do not call `TL.play()`. The renderer seeks the timeline frame by frame.
  For viewing in a browser, add `?play` to the URL: `if (location.search.includes('play')) TL.play();`

## Fonts
- Never Arial, Helvetica, Times, or plain system-ui.
- Load fonts with `<link rel="stylesheet" href="../../vendor/fonts/fonts.css">`. Available families:
  Inter, Space Grotesk, Sora, Manrope, Archivo Black, Bebas Neue, Syne, Playfair Display, DM Serif Display, Fraunces, Instrument Serif, JetBrains Mono.
- Use only the fonts and colours of the chosen style pack.

## Style packs (`vendor/style_packs.json`)
Each pack has a display font, body font, type scale (px), weights, letter-spacing and a palette (background, text, accent).

| pack | display / body | palette (bg / text / accent) |
| --- | --- | --- |
| editorial | Playfair Display / Inter | #F4EFE6 / #1B1A17 / #B4442C |
| tech-launch | Space Grotesk / Inter | #0B0D12 / #E8ECF4 / #5B8CFF |
| bold-sports | Bebas Neue / Archivo Black | #111111 / #FFFFFF / #E8FF3A |
| luxury | DM Serif Display / Manrope | #0E0C0A / #EDE3D1 / #C9A45C |
| playful | Syne / Sora | #FFE8D6 / #2B1B4A / #FF4F7B |
| minimal-mono | JetBrains Mono / JetBrains Mono | #F2F2F0 / #111111 / #FF3B00 |
| soft-saas | Sora / Manrope | #EEF1FB / #1A1F36 / #6C5CE7 |
| gallery-serif | Instrument Serif / Space Grotesk | #1C2B24 / #EAF0E6 / #E7B76A |
| warm-modern | Fraunces / Inter | #FBF3E4 / #3A2416 / #E0662E |

Tints and shades of the palette colours (via opacity or rgba) are fine; new hues are not.

## Skeleton
```html
<!doctype html>
<html>
<head>
<!-- pack: tech-launch -->
<meta charset="utf-8">
<link rel="stylesheet" href="../../vendor/fonts/fonts.css">
<style>
  body { margin: 0; background: #0B0D12; }
  #stage { position: relative; width: 1280px; height: 720px; overflow: hidden; background: #0B0D12; }
  #box { position: absolute; left: 540px; top: 260px; width: 200px; height: 200px; border-radius: 24px; background: #5B8CFF; }
</style>
</head>
<body>
<div id="stage"><div id="box"></div></div>
<script src="../../vendor/gsap.min.js"></script>
<script>
document.fonts.ready.then(() => {
  const tl = gsap.timeline({ paused: true });
  tl.from("#box", { x: -400, autoAlpha: 0, duration: 0.9, ease: "power3.out" })
    .to({}, { duration: 0.6 }); // final hold
  window.TL = tl;
  if (location.search.includes("play")) tl.play();
});
</script>
</body>
</html>
```

## Templates (category `template`)
Reusable explainer graphics (VS splits, stat duels, leaderboards) for YouTube-style videos, made to overlay footage.

- **DATA block first.** The script starts with one `const DATA = {...}` holding every name, number, colour and label. The script fills the DOM from DATA before building the timeline, so editing DATA is the only change needed. Layout must survive longer or shorter names (auto widths, no hardcoded text widths).
  ```js
  const DATA = {
    title: "Coding benchmark",
    a: { name: "Nova", color: "#4D6BFE", stat: 92 },
    b: { name: "Apex", color: "#10A37F", stat: 88 },
  };
  ```
- **Logo slots.** Each logo is `<div class="slot" id="slotA"><svg id="logoA" viewBox="0 0 100 100">…</svg></div>` with the svg at `width:100%; height:100%`. Animate the `.slot` wrapper, never the svg's inner shapes, so any pasted SVG logo works. Bank versions use neutral placeholder marks and made-up names (Nova, Apex, Orbit, Quill, Kite), never real brands.
- **Brand colours.** `DATA.*.color` may be used as accents in addition to the pack palette (bars, glows, plates). Everything else stays in the pack.
- **Overlay-ready.** The pack background lives in `<div id="bg">` (first child of `#stage`, full size). `render.py --alpha` hides `#bg` and exports transparent video, so every element must read on any footage: put text on its own plate/panel, or use strong contrast; no hairline grey text floating on nothing.
- Render with `python tools/render.py entries/<id> --alpha` and check `alpha_check.png` (mid and end frames on a checkerboard).

## Vertical format (Shorts / Reels / TikTok)
- Second line in `<head>`: `<!-- format: vertical -->`, and tag the entry `vertical` in meta.json.
- `#stage` is 720x1280 (exported at 1080x1920 with `--alpha`). Everything else in this contract applies.
- Compose for a phone: stack things vertically (A above B, not side by side), big type (a headline line holds about 4-6 words), centred on the vertical axis.
- Safe zones: platform UI covers the top 8%, the bottom 20% and the right 14% below 40% height. Keep all text out of them; the renderer flags text there.
- Hook within the first 0.5s. Prefer seamless loops (last frame equals first) over a final hold; Shorts replay.

## Declared layering
Backing elements that are meant to sit behind content (panels, column highlights, axis lines, orbit rings, plates) get `data-layer="back"`. The overlap check skips only the marked element itself, not its children: mark the plate, and the logos and text sitting on it are still checked. Shapes inside a marked `<svg>` count as part of that backing graphic.
