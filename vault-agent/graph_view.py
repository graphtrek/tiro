"""Render a Vault's link graph as a self-contained HTML page: a force-directed
canvas view of the [[wikilink]] network, physics tuned to the vault's own
.obsidian/graph.json when it has one (see Vault.graph_settings).

    html = render_graph_html(vault.graph(), vault.graph_settings(), vault.root.name)

No external assets (fonts, scripts, CDNs) - opens straight from a file:// path,
which is what cli.py's `/graph` does; web.py instead serves it from GET /graph
since it's already running a server. Same palette as static/index.html (the
terminal), so the graph reads as the same tool, not a bolted-on view.
"""

from __future__ import annotations

import json

# A named (not "_blank") window target for every link that leaves the graph page
# for the terminal - the back link and each note's "read in terminal" icon. Named
# windows are reused by the browser across clicks, so repeatedly sending notes to
# the terminal updates that one tab instead of spawning a pile of them, while the
# graph's own tab is never navigated away from or replaced.
TERMINAL_TAB_NAME = "vault-agent-terminal"

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__VAULT_NAME__ — graph</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --fg: #e6edf3; --dim: #8b949e;
    --cyan: #56d4dd; --blue: #79c0ff; --red: #ff7b72;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; overflow: hidden; }
  body {
    background: var(--bg); color: var(--fg);
    font: 13px/1.5 "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  }
  .app { display: grid; grid-template-rows: auto 1fr; height: 100vh; }
  .topbar {
    display: flex; align-items: center; gap: 1rem;
    padding: 8px 14px; background: var(--panel); border-bottom: 1px solid var(--border);
  }
  .topbar .title { color: var(--cyan); font-weight: bold; white-space: nowrap; }
  .topbar a.back {
    color: var(--dim); text-decoration: none; white-space: nowrap;
    border: 1px solid var(--border); border-radius: 4px; padding: 4px 10px;
  }
  .topbar a.back:hover { border-color: var(--cyan); color: var(--cyan); }
  .topbar .stat { color: var(--dim); white-space: nowrap; }
  .topbar input {
    flex: 1; max-width: 20rem; background: var(--bg); border: 1px solid var(--border);
    border-radius: 4px; color: var(--fg); padding: 4px 8px; font: inherit;
  }
  .topbar input:focus { outline: 1px solid var(--cyan); }
  .topbar button {
    background: transparent; border: 1px solid var(--border); color: var(--fg);
    border-radius: 4px; padding: 4px 10px; font: inherit; cursor: pointer;
  }
  .topbar button:hover { border-color: var(--cyan); color: var(--cyan); }
  .legend { margin-left: auto; display: flex; gap: 14px; color: var(--dim); white-space: nowrap; }
  .legend .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; }
  .legend .dot.r { background: var(--blue); }
  .legend .dot.u { background: transparent; border: 1px dashed var(--red); }
  .stage { position: relative; overflow: hidden; }
  canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  canvas.panning { cursor: grabbing; }
  .panel {
    position: absolute; top: 12px; right: 12px; width: 260px; max-height: calc(100% - 24px);
    overflow-y: auto; background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 12px 14px; display: none;
  }
  .panel.open { display: block; }
  .panel .head-row { display: flex; align-items: flex-start; gap: 6px; padding-right: 18px; }
  .panel h2 { flex: 1; font-size: 13px; margin: 0 0 4px; color: var(--blue); word-break: break-word; }
  .panel h2.unresolved { color: var(--red); }
  .panel .read-in-terminal {
    flex: none; background: none; border: 1px solid var(--border); border-radius: 4px;
    color: var(--dim); cursor: pointer; font-size: 12px; line-height: 1; padding: 3px 5px;
  }
  .panel .read-in-terminal:hover { border-color: var(--cyan); color: var(--cyan); }
  .panel .read-in-terminal:disabled { opacity: .3; cursor: default; border-color: var(--border); color: var(--dim); }
  .panel .status { color: var(--dim); font-size: 11px; margin-bottom: 10px; }
  .panel h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--dim); margin: 10px 0 4px; }
  .panel ul { list-style: none; margin: 0; padding: 0; }
  .panel li { border-top: 1px solid var(--border); padding: 4px 0; }
  .panel li:first-child { border-top: none; }
  .panel button.link { background: none; border: none; color: var(--fg); cursor: pointer; font: inherit; padding: 0; text-align: left; }
  .panel button.link:hover { color: var(--cyan); }
  .panel .close { position: absolute; top: 6px; right: 8px; background: none; border: none; color: var(--dim); font-size: 15px; cursor: pointer; }
  .panel .close:hover { color: var(--fg); }
  .hint { position: absolute; left: 12px; bottom: 10px; color: var(--dim); font-size: 11px; }
</style>
</head>
<body>
<div class="app">
  <div class="topbar">
    __BACK_LINK__
    <span class="title">__VAULT_NAME__ — graph</span>
    <span class="stat" id="stat"></span>
    <input id="search" type="text" placeholder="filter notes…" autocomplete="off">
    <button id="reset">reset view</button>
    <span class="legend">
      <span><i class="dot r"></i>note</span>
      <span><i class="dot u"></i>unresolved link</span>
    </span>
  </div>
  <div class="stage">
    <canvas id="c"></canvas>
    <div class="panel" id="panel">
      <button class="close" id="panelClose">&times;</button>
      <div class="head-row">
        <h2 id="pTitle"></h2>
        <button class="read-in-terminal" id="pRead" title="read in terminal" aria-label="read this note in the terminal">&#8250;_</button>
      </div>
      <div class="status" id="pStatus"></div>
      <h3 id="outH"></h3>
      <ul id="outL"></ul>
      <h3 id="inH"></h3>
      <ul id="inL"></ul>
    </div>
    <div class="hint">drag to pan · scroll to zoom · drag a note to move it · click for details</div>
  </div>
</div>
<script>
(function () {
  const GRAPH = __GRAPH_JSON__;
  const SETTINGS = __SETTINGS_JSON__;
  const BACK_URL = __BACK_URL_JSON__;

  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  const stage = canvas.parentElement;
  document.getElementById("stat").textContent =
    GRAPH.nodes.length + " notes · " + GRAPH.links.length + " links";

  const linkDistance = SETTINGS.linkDistance || 250;
  const repelStrength = SETTINGS.repelStrength || 10;
  const linkStrength = SETTINGS.linkStrength || 1;
  const centerStrength = SETTINGS.centerStrength || 0.5;
  const nodeSizeMultiplier = SETTINGS.nodeSizeMultiplier || 1;
  const lineSizeMultiplier = SETTINGS.lineSizeMultiplier || 1;

  const byId = new Map();
  const nodes = GRAPH.nodes.map((n, i) => {
    const a = (i / GRAPH.nodes.length) * Math.PI * 2;
    const r = 120 + Math.random() * 60;
    const node = {
      ...n, x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0,
      radius: (n.resolved ? 5 : 4) + Math.sqrt(n.degree || 0) * 3.2 * nodeSizeMultiplier,
    };
    byId.set(n.id, node);
    return node;
  });
  const links = GRAPH.links
    .map((l) => ({ source: byId.get(l.source), target: byId.get(l.target) }))
    .filter((l) => l.source && l.target);

  const neighbors = new Map();
  nodes.forEach((n) => neighbors.set(n.id, new Set()));
  links.forEach((l) => {
    neighbors.get(l.source.id).add(l.target.id);
    neighbors.get(l.target.id).add(l.source.id);
  });

  let camX = 0, camY = 0, camScale = 1, dpr = Math.max(1, window.devicePixelRatio || 1);

  function resize() {
    const rect = stage.getBoundingClientRect();
    dpr = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
  }
  window.addEventListener("resize", resize);
  resize();

  function toScreen(x, y) {
    const r = stage.getBoundingClientRect();
    return { x: (x - camX) * camScale + r.width / 2, y: (y - camY) * camScale + r.height / 2 };
  }
  function toWorld(sx, sy) {
    const r = stage.getBoundingClientRect();
    return { x: (sx - r.width / 2) / camScale + camX, y: (sy - r.height / 2) / camScale + camY };
  }

  function step() {
    const repelK = repelStrength * 260;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      if (a.fixed) continue;
      let fx = 0, fy = 0;
      for (let j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 < 1) d2 = 1;
        const f = repelK / d2, d = Math.sqrt(d2);
        fx += (dx / d) * f; fy += (dy / d) * f;
      }
      fx += -a.x * centerStrength * 0.012;
      fy += -a.y * centerStrength * 0.012;
      a.vx = (a.vx + fx) * 0.82;
      a.vy = (a.vy + fy) * 0.82;
    }
    for (const l of links) {
      let dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
      let d = Math.sqrt(dx * dx + dy * dy) || 1;
      const diff = (d - linkDistance) * linkStrength * 0.02;
      const ux = dx / d, uy = dy / d;
      if (!l.source.fixed) { l.source.vx += ux * diff; l.source.vy += uy * diff; }
      if (!l.target.fixed) { l.target.vx -= ux * diff; l.target.vy -= uy * diff; }
    }
    for (const n of nodes) {
      if (n.fixed) continue;
      n.x += n.vx; n.y += n.vy;
    }
  }

  let selected = null, hovered = null;

  function draw() {
    const rect = stage.getBoundingClientRect();
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const focus = selected || hovered;
    const active = focus ? neighbors.get(focus.id) : null;

    ctx.lineWidth = lineSizeMultiplier;
    for (const l of links) {
      const a = toScreen(l.source.x, l.source.y), b = toScreen(l.target.x, l.target.y);
      const dim = focus && focus.id !== l.source.id && focus.id !== l.target.id;
      const phantom = !l.source.resolved || !l.target.resolved;
      ctx.strokeStyle = focus && !dim ? "#56d4dd" : (phantom ? "rgba(255,123,114,0.35)" : "rgba(230,237,243,0.16)");
      ctx.globalAlpha = dim ? 0.15 : 1;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.globalAlpha = 1;

    const showLabel = camScale > 0.55;
    for (const n of nodes) {
      const p = toScreen(n.x, n.y);
      const dim = focus && focus.id !== n.id && !active.has(n.id);
      ctx.globalAlpha = dim ? 0.25 : 1;
      const r = n.radius * Math.min(1.4, Math.max(0.7, camScale));
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = n.resolved ? "#79c0ff" : "transparent";
      ctx.fill();
      if (!n.resolved) {
        ctx.strokeStyle = "#ff7b72"; ctx.setLineDash([2, 2]); ctx.lineWidth = 1.4;
        ctx.stroke(); ctx.setLineDash([]);
      }
      if (focus && focus.id === n.id) {
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 3, 0, Math.PI * 2);
        ctx.strokeStyle = n.resolved ? "#79c0ff" : "#ff7b72"; ctx.lineWidth = 1.5; ctx.stroke();
      }
      if (showLabel || focus === n) {
        ctx.font = "11px ui-monospace, 'SF Mono', Menlo, Consolas, monospace";
        ctx.fillStyle = focus === n ? (n.resolved ? "#79c0ff" : "#ff7b72") : "#8b949e";
        ctx.textBaseline = "middle";
        ctx.fillText(n.label, p.x + r + 5, p.y);
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  (function loop() { step(); draw(); requestAnimationFrame(loop); })();

  let panning = false, panStart = null, camStart = null, draggingNode = null, downPos = null, moved = false;

  function nodeAt(sx, sy) {
    const w = toWorld(sx, sy);
    let best = null, bestD = Infinity;
    for (const n of nodes) {
      const dx = n.x - w.x, dy = n.y - w.y, d = Math.sqrt(dx * dx + dy * dy);
      const hitR = n.radius + 6 / camScale;
      if (d < hitR && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (e) => {
    const r = canvas.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
    downPos = { sx, sy }; moved = false;
    const hit = nodeAt(sx, sy);
    if (hit) {
      draggingNode = hit; hit.fixed = true; canvas.setPointerCapture(e.pointerId);
    } else {
      panning = true; panStart = { x: e.clientX, y: e.clientY }; camStart = { x: camX, y: camY };
      canvas.classList.add("panning");
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
    if (downPos && (Math.abs(sx - downPos.sx) > 3 || Math.abs(sy - downPos.sy) > 3)) moved = true;
    if (draggingNode) {
      const w = toWorld(sx, sy);
      draggingNode.x = w.x; draggingNode.y = w.y; draggingNode.vx = 0; draggingNode.vy = 0;
      return;
    }
    if (panning) {
      camX = camStart.x - (e.clientX - panStart.x) / camScale;
      camY = camStart.y - (e.clientY - panStart.y) / camScale;
      return;
    }
    hovered = nodeAt(sx, sy);
    canvas.style.cursor = hovered ? "pointer" : "grab";
  });
  function endInteraction() {
    if (draggingNode) {
      draggingNode.fixed = false;
      if (!moved) selectNode(draggingNode);
      draggingNode = null;
    }
    if (panning) { panning = false; canvas.classList.remove("panning"); }
    downPos = null;
  }
  canvas.addEventListener("pointerup", endInteraction);
  canvas.addEventListener("pointercancel", endInteraction);
  canvas.addEventListener("pointerleave", () => { hovered = null; });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
    const before = toWorld(sx, sy);
    camScale = Math.min(4, Math.max(0.15, camScale * Math.exp(-e.deltaY * 0.0012)));
    const after = toWorld(sx, sy);
    camX += before.x - after.x; camY += before.y - after.y;
  }, { passive: false });

  document.getElementById("reset").addEventListener("click", () => {
    camX = 0; camY = 0; camScale = 1; closePanel();
  });

  function selectNode(n) { selected = n; openPanel(n); }

  const readBtn = document.getElementById("pRead");
  if (!BACK_URL) {
    readBtn.style.display = "none";
  } else {
    readBtn.addEventListener("click", () => {
      if (!selected || !selected.resolved) return;
      const sep = BACK_URL.includes("?") ? "&" : "?";
      const url = BACK_URL + sep + "read=" + encodeURIComponent(selected.id);
      // A named target, not "_blank": reuses the terminal tab across clicks instead
      // of piling up a new one each time, and never touches this graph tab.
      window.open(url, "__TERMINAL_TAB_NAME__", "noopener,noreferrer");
    });
  }

  function openPanel(n) {
    document.getElementById("pTitle").textContent = n.label;
    document.getElementById("pTitle").className = n.resolved ? "" : "unresolved";
    document.getElementById("pStatus").textContent =
      n.resolved ? "note" : "unresolved link — no matching note";
    if (BACK_URL) {
      readBtn.disabled = !n.resolved;
      readBtn.title = n.resolved ? "read in terminal" : "no note to read — unresolved link";
    }

    const out = links.filter((l) => l.source.id === n.id).map((l) => l.target);
    const inn = links.filter((l) => l.target.id === n.id).map((l) => l.source);
    document.getElementById("outH").textContent = "links out (" + out.length + ")";
    document.getElementById("inH").textContent = "linked from (" + inn.length + ")";
    const outL = document.getElementById("outL"), inL = document.getElementById("inL");
    outL.innerHTML = ""; inL.innerHTML = "";
    out.forEach((t) => outL.appendChild(li(t)));
    inn.forEach((t) => inL.appendChild(li(t)));
    document.getElementById("panel").classList.add("open");
  }
  function li(target) {
    const el = document.createElement("li"), btn = document.createElement("button");
    btn.className = "link"; btn.textContent = target.label;
    btn.addEventListener("click", () => selectNode(target));
    el.appendChild(btn);
    return el;
  }
  function closePanel() { selected = null; document.getElementById("panel").classList.remove("open"); }
  document.getElementById("panelClose").addEventListener("click", closePanel);

  document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    hovered = q ? nodes.find((n) => n.label.toLowerCase().includes(q)) || null : null;
  });
})();
</script>
</body>
</html>
"""


def render_graph_html(
    graph: dict, settings: dict, vault_name: str, back_url: str | None = None
) -> str:
    """Fill the template with this vault's graph data - the JSON blobs are the only
    per-call variation, everything else (CSS, physics/interaction JS) is static.

    back_url, when given, adds a "← terminal" link to that URL in the topbar, and a
    per-note "read in terminal" icon in the details panel that navigates to
    `back_url?read=<note id>` - pass it from web.py (back to "/", the chat page) but
    not from cli.py, which opens this from a temp file with no running terminal to
    link back to."""
    html = _TEMPLATE.replace("__VAULT_NAME__", _esc(vault_name))
    html = html.replace("__GRAPH_JSON__", _json_for_script(graph))
    html = html.replace("__SETTINGS_JSON__", _json_for_script(settings))
    html = html.replace("__BACK_URL_JSON__", _json_for_script(back_url))
    html = html.replace("__TERMINAL_TAB_NAME__", TERMINAL_TAB_NAME)
    back_link = (
        f'<a class="back" href="{_esc(back_url)}" target="{TERMINAL_TAB_NAME}" '
        f'rel="noopener noreferrer">&larr; terminal</a>'
        if back_url
        else ""
    )
    html = html.replace("__BACK_LINK__", back_link)
    return html


def _json_for_script(data: object) -> str:
    """json.dumps, with "</" broken up so a note titled e.g. "</script><script>..."
    can't terminate the embedding <script> tag early."""
    return json.dumps(data).replace("</", "<\\/")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
