"""Review gallery: keep / reject / tag / holdout entries from the browser.

Usage:
    python tools/gallery.py [--port 8765] [--no-open]

Writes anim_bank/gallery.html and serves anim_bank on localhost.
GET  /api/entries          -> list of meta.json (+ render state)
POST /api/meta/<id>        -> merge JSON body {status, tags, holdout} into meta.json
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import webbrowser
from urllib.parse import unquote
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent
ENTRIES = BANK / "entries"
EDITABLE = {"status", "tags", "holdout", "reason"}
# why a reject was rejected: one key in the gallery after R
REASONS = {"broken", "dull", "type", "timing", "look"}

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>anim_bank gallery</title>
<style>
  body { margin: 0; font: 14px/1.45 Inter, sans-serif; background: #15161a; color: #e6e6e6; }
  @font-face { font-family: Inter; src: url('vendor/fonts/Inter.woff2'); font-weight: 100 900; }
  header { display: flex; gap: 8px; align-items: center; padding: 10px 16px; background: #1d1f24; flex-wrap: wrap; }
  header button { background: #2a2d34; color: #ddd; border: 1px solid #3a3e47; border-radius: 6px; padding: 5px 10px; cursor: pointer; font: inherit; }
  header button.on { background: #5b8cff; border-color: #5b8cff; color: #fff; }
  header input { background: #101114; color: #eee; border: 1px solid #3a3e47; border-radius: 6px; padding: 5px 8px; font: inherit; width: 150px; }
  .count { margin-left: auto; color: #999; }
  main { padding: 16px; max-width: 1340px; margin: 0 auto; }
  img.gif { display: block; max-width: 100%; max-height: 70vh; width: auto; height: auto; background: #000; border-radius: 6px; }
  div.gif { width: 100%; max-width: 1280px; aspect-ratio: 16/9; background: #000; border-radius: 6px; }
  .row { display: flex; gap: 16px; align-items: baseline; margin: 12px 0 4px; flex-wrap: wrap; }
  .id { color: #888; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .prompt { font-size: 20px; color: #fff; }
  .badge { padding: 2px 8px; border-radius: 99px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
  .pending { background: #444; } .keep { background: #2e8b57; } .reject { background: #b33a3a; } .hold { background: #b8860b; }
  #tags { width: 100%; max-width: 600px; background: #101114; color: #eee; border: 1px solid #3a3e47; border-radius: 6px; padding: 6px 8px; font: inherit; }
  .help { color: #777; font-size: 12px; margin-top: 10px; }
  .why { background: #b33a3a22; border: 1px solid #b33a3a; border-radius: 8px; padding: 10px 14px; margin: 10px 0; font-size: 15px; }
  .why b { display: inline-block; min-width: 18px; padding: 1px 6px; margin: 0 2px 0 10px; border-radius: 4px; background: #b33a3a; color: #fff; text-align: center; }
  .reason { background: #6b2a2a; }
  .links a { color: #8fb0ff; margin-right: 12px; font-size: 12px; }
  pre { background: #0e0f12; padding: 10px; border-radius: 6px; font-size: 12px; overflow-x: auto; color: #bbb; }
  .cmp img.gif { max-width: 100%; max-height: 60vh; }
  .cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .cmp .prompt { font-size: 15px; }
  .empty { color: #888; padding: 40px; text-align: center; }
</style></head>
<body>
<header>
  <button data-f="all">all</button><button data-f="pending" class="on">pending</button>
  <button data-f="keep">keep</button><button data-f="reject">reject</button><button data-f="holdout">holdout</button>
  <span style="width:16px"></span>
  compare <input id="ca" placeholder="entry id A"><input id="cb" placeholder="entry id B"><button id="cmpgo">show</button>
  <span class="count" id="count"></span>
</header>
<main id="main"></main>
<script>
let all = [], list = [], idx = 0, filter = 'pending', mode = 'one';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const gif = e => `entries/${e.id}/preview.gif?v=${e.mtime}`;

async function load(keepId) {
  all = await (await fetch('/api/entries')).json();
  apply(keepId);
}
function apply(keepId) {
  list = all.filter(e => filter === 'all' ? true : filter === 'holdout' ? e.holdout : e.status === filter);
  if (keepId) { const i = list.findIndex(e => e.id === keepId); idx = i >= 0 ? i : Math.min(idx, list.length - 1); }
  idx = Math.max(0, Math.min(idx, list.length - 1));
  document.querySelectorAll('header [data-f]').forEach(b => b.classList.toggle('on', b.dataset.f === filter));
  render();
}
function render() {
  mode = 'one';
  const c = all.reduce((a, e) => (a[e.status] = (a[e.status] || 0) + 1, a), {});
  const why = all.filter(e => e.reason).reduce((a, e) => (a[e.reason] = (a[e.reason] || 0) + 1, a), {});
  const whyTxt = Object.keys(why).length ? ' (' + Object.entries(why).map(([r, n]) => `${r} ${n}`).join(', ') + ')' : '';
  $('#count').textContent = `${list.length ? idx + 1 : 0}/${list.length} shown · ${all.length} total · keep ${c.keep||0} · reject ${c.reject||0}${whyTxt} · pending ${c.pending||0} · holdout ${all.filter(e=>e.holdout).length}`;
  const e = list[idx];
  if (!e) { $('#main').innerHTML = '<div class="empty">nothing in this filter</div>'; return; }
  $('#main').innerHTML = `
    ${e.rendered ? `<img class="gif" src="${gif(e)}">` : `<div class="gif empty">not rendered${e.error ? ': ' + esc(e.error) : ''}</div>`}
    ${asking ? `<div class="why">Why reject? ${Object.entries(REASONS).map(([k, v]) => `<b>${k.toUpperCase()}</b>${v}`).join(' ')} <span style="color:#999;margin-left:12px">Esc skip</span></div>` : ''}
    <div class="row"><span class="badge ${e.status}">${e.status}</span>${e.reason ? `<span class="badge reason">${esc(e.reason)}</span>` : ''}${e.holdout ? '<span class="badge hold">holdout</span>' : ''}
      <span class="prompt">${esc(e.prompt)}</span></div>
    <div class="row"><span class="id">${esc(e.id)} · ${esc(e.source)} · ${esc(e.created)}</span>
      <span class="links"><a href="entries/${e.id}/anim.html?play" target="_blank">open live</a><a href="entries/${e.id}/filmstrip.png" target="_blank">filmstrip</a><a href="entries/${e.id}/onion.png" target="_blank">onion</a><a href="entries/${e.id}/report.txt" target="_blank">report</a>${e.alpha ? `<a href="entries/${e.id}/alpha_check.png" target="_blank">alpha</a>` : ''}</span></div>
    <input id="tags" value="${esc((e.tags || []).join(', '))}" placeholder="tags, comma separated (Enter saves)">
    <div class="help">K keep · R reject (then a reason key) · H holdout · T edit tags (Enter saves, Esc leaves) · ←/→ prev/next</div>`;
  $('#tags').addEventListener('keydown', ev => {
    if (ev.key === 'Enter') { save(e, { tags: ev.target.value.split(',').map(s => s.trim()).filter(Boolean) }); ev.target.blur(); }
    if (ev.key === 'Escape') ev.target.blur();
    ev.stopPropagation();
  });
}
async function save(e, patch) {
  const r = await fetch('/api/meta/' + encodeURIComponent(e.id), { method: 'POST', body: JSON.stringify(patch) });
  if (!r.ok) { alert('save failed: ' + await r.text()); return; }
  Object.assign(e, await r.json());
}
const REASONS = { b: 'broken', d: 'dull', t: 'type', s: 'timing', l: 'look' };
let asking = false;
async function reject() {
  const e = list[idx]; if (!e) return;
  await save(e, { status: 'reject' });
  asking = true; render();
}
async function answer(key) {
  const e = list[idx]; asking = false;
  if (e && REASONS[key]) await save(e, { reason: REASONS[key] });
  const next = list[idx + 1];
  apply(next ? next.id : null);
}
async function setStatus(s) {
  const e = list[idx]; if (!e) return;
  await save(e, { status: s });
  // advance; the entry may leave the current filter
  const next = list[idx + 1];
  apply(next ? next.id : null);
}
function compare(a, b) {
  const A = all.find(e => e.id === a), B = all.find(e => e.id === b);
  if (!A || !B) { alert('unknown id: ' + (!A ? a : b)); return; }
  mode = 'cmp';
  const col = e => `<div><img class="gif" src="${gif(e)}"><div class="row"><span class="badge ${e.status}">${e.status}</span><span class="prompt">${esc(e.prompt)}</span></div><div class="id">${esc(e.id)} · ${esc(e.source)}</div><pre>${esc(e.report || '')}</pre></div>`;
  $('#main').innerHTML = `<div class="cmp">${col(A)}${col(B)}</div><div class="help">Esc returns to single view</div>`;
}
document.querySelectorAll('header [data-f]').forEach(b => b.onclick = () => { filter = b.dataset.f; idx = 0; apply(); });
$('#cmpgo').onclick = () => compare($('#ca').value.trim(), $('#cb').value.trim());
document.addEventListener('keydown', ev => {
  if (ev.target.tagName === 'INPUT') return;
  if (mode === 'cmp') { if (ev.key === 'Escape') render(); return; }
  const k = ev.key.toLowerCase(), e = list[idx];
  if (asking) { ev.preventDefault(); answer(k); return; }
  if (k === 'k') setStatus('keep');
  else if (k === 'r') reject();
  else if (k === 'h' && e) save(e, { holdout: !e.holdout }).then(render);
  else if (k === 't') { ev.preventDefault(); const t = $('#tags'); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } }
  else if (ev.key === 'ArrowRight') { idx = Math.min(idx + 1, list.length - 1); render(); }
  else if (ev.key === 'ArrowLeft') { idx = Math.max(idx - 1, 0); render(); }
});
const q = new URLSearchParams(location.search);
load().then(() => { if (q.get('a') && q.get('b')) compare(q.get('a'), q.get('b')); });
</script>
</body></html>
"""


def entry_info(d: Path) -> dict | None:
    mp = d / "meta.json"
    if not mp.exists():
        return None
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.setdefault("id", d.name)
    gif = d / "preview.gif"
    err = d / "render_error.txt"
    rep = d / "report.txt"
    meta["rendered"] = gif.exists()
    meta["mtime"] = int(gif.stat().st_mtime) if gif.exists() else 0
    meta["error"] = err.read_text(encoding="utf-8").splitlines()[0] if err.exists() else None
    meta["report"] = rep.read_text(encoding="utf-8") if rep.exists() else ""
    meta["alpha"] = (d / "alpha_check.png").exists()
    return meta


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/api/entries":
            items = [i for d in sorted(ENTRIES.iterdir()) if d.is_dir() and (i := entry_info(d))]
            items.sort(key=lambda m: (m.get("created", ""), m["id"]))
            return self._json(200, items)
        if route in ("/", ""):
            self.path = "/gallery.html" + self.path[len(route):]
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/meta/"):
            return self._json(404, {"error": "not found"})
        eid = unquote(self.path[len("/api/meta/"):])
        d = (ENTRIES / eid).resolve()
        if d.parent != ENTRIES.resolve() or not (d / "meta.json").exists():
            return self._json(404, {"error": f"no entry {eid}"})
        patch = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        for k, v in patch.items():
            if k not in EDITABLE:
                continue
            if k == "status" and v not in ("pending", "keep", "reject"):
                return self._json(400, {"error": f"bad status {v}"})
            if k == "reason" and v is not None and v not in REASONS:
                return self._json(400, {"error": f"bad reason {v}"})
            meta[k] = v
        if meta.get("status") != "reject":
            meta.pop("reason", None)  # reasons only describe rejects
        (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
        return self._json(200, meta)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()
    (BANK / "gallery.html").write_text(PAGE, encoding="utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Handler, directory=str(BANK)))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"gallery: {url}   (compare: {url}?a=<id>&b=<id>)   Ctrl+C to stop")
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
