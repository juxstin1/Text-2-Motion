# Handoff (2026-10-23)

## Where things stand

- **Bank:** 85 Claude animations, all rated (61 keep / 24 reject, every reject has a reason), 5 holdouts: shape-drop-bounce, record-stamp, cta-button-pop, kinetic-three-words, countdown-go.
- **Experiment 1 (baseline) done:** Gemma 4 12B, 3 prompts, 10 calls. Inconclusive (1–1). Write-up: [docs/experiments/2026-10-23-gemma-baseline.md](docs/experiments/2026-10-23-gemma-baseline.md). Human verdict on the best output (record-stamp 0-shot): "perfect, timing a bit too quick, bland, first of many."
- **Fixed since the baseline (committed with this handoff):**
  - Checker: 3 new defects. `visibility` (animated but never visible), `cut off` (ends >15% cropped by its container/svg), `ending` (final hold >1.0s or >40% of runtime; threshold from the 61 keepers, max 0.86s / 37%). The ending hint fixes pacing, never length: "Slow the main action… then hold for under 1.0s".
  - Fixtures: `uv run tools/test_checker.py` = 12 PASS, 1 XFAIL (occlusion).
  - Runner: `--think on|off`; a reply that thinks until max_tokens is retried once with thinking off (`chat_template_kwargs.enable_thinking=false`, verified on Gemma). meta.json now stores `gen` (tokens, seconds, reasoning size, temperature, max_tokens, fallback). Repair prompt targets DEFECT lines only.

## Not finished

1. **Keeper check of the new rules (done, 4 false alarms to fix):** full re-render, the new checks flag 4/61 keepers, 3/24 rejects, 6/8 Gemma attempts.
   - Rejects (plausible): modal-scale-in (frozen; rated dull), headline-word-cycle (cut off), heart-like-burst (cut off).
   - Keepers (false alarms, fix the rule, then freeze each as a must-stay-clean fixture):
     - circle-iris-transition: `#iris` "cut off". It's an 800px-radius fill meant to overflow → exempt elements larger than the stage.
     - scoreboard-rounds: `#sideB div.glow` "never visible". Leader-only glow, side B never leads, already `data-layer="back"` → exempt back layers from never-visible.
     - vs-split (never visible) and winner-reveal (cut off): not inspected yet; likely the same two causes.
2. **Experiment 2 not started:** run it with the command below.
3. **Gemma's 8 outputs are unrated** (gallery → pending).

## Run Experiment 2

Needs the Gemma llama-server on port 8090 (it shares one slot with the Vision_Paper session).

```bash
uv run tools/test_checker.py                                   # must be green first
uv run tools/run_experiment.py --url http://127.0.0.1:8090/v1  # 3 holdouts, 3-shot, up to 3 attempts each (<=9 calls)
uv run tools/gallery.py                                        # judge: pending filter; compare ?a=<holdout>&b=<gemma id>
```

Add `--shots 0 3` for both conditions. Log: `docs/experiments/<date>-run.log`. Write results next to the baseline write-up.

Keeper hit list after a full re-render:

```bash
uv run python -c "import json,pathlib as p;[print(m['status'],d.name,[k for k,v in (('never',c['never_visible']),('cut',c['cut_off']),('frozen',c['frozen']['defect'])) if v]) for d in sorted(p.Path('entries').iterdir()) for m in [json.load(open(d/'meta.json'))] if m['source']=='claude' and (d/'motion.json').exists() for c in [json.load(open(d/'motion.json'))['checks']] if c['never_visible'] or c['cut_off'] or c['frozen']['defect']]"
```

## Next, in order

1. Finish the keeper check (above); fix or fixture the circle-iris hit.
2. Experiment 2: same 3 prompts, 3-shot, honest repair feedback. Did repairs fix the named defects this time?
3. Retrieval: motion tags derived from motion.json (drop, slam, squash, reveal…) + a request verb map (stamp → slam) + a minimum match score (send 0–3 examples, not always 3). Judge on **5 fresh holdouts**, not the current five, so it isn't tuned to its own test.
4. Occlusion-aware overlap (fixture `gap-occlusion-iris`).
5. Pilot: can a VLM predict keep/reject from filmstrip + report better than from raw frames? Labels and reasons already exist.

## Rules learned (keep following them)

- When a model breaks something in a new way and the checker misses it, freeze the anim.html in `fixtures/` with an `expect.json`. Checker changes must keep `test_checker.py` green.
- Classify findings as DEFECT (fix) vs note (fact). Never reward timid motion; a noisy checker makes agents and models shrink the design.
- Thresholds come from the human ratings, not guesses.
- Don't change the checker or runner mid-experiment; record a baseline, then fix, then rerun.
- Never `page.evaluate` something that returns a GSAP timeline (wrap in `{ ...; }` or return a boolean).
- Edit tools with the editor or a patch file, not shell heredocs with `\n` inside; syntax-check before a running experiment picks them up.
- "Sprite sheet" = `filmstrip.png`. User taste: motion-first, short holds, no calm title cards; remaining weakness is look (colour/composition), not motion or type.
