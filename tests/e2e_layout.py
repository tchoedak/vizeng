"""Browser E2E for diagram legibility. Starts its own server; needs Python Playwright.

    python3 tests/e2e_layout.py [screenshot-dir]

Loads a diagram written the way an agent writes one (no positions, long edge labels,
edges that skip layers, a cycle, two unrelated clusters) and measures the rendered SVG,
not the layout code: whatever the implementation, these are the things a reader sees.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT = Path(__file__).resolve().parent.parent / "plugins/vizeng/skills/architecture/scripts/vizeng.py"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
OUT.mkdir(parents=True, exist_ok=True)


def n(id_, label, role, group=None):
    d = {"id": id_, "label": label, "card": {"role": role, "purpose": f"{label} does its one job."}}
    if group:
        d["group"] = group
    return d


def e(id_, a, b, rel, label="", **kw):
    return {"id": id_, "from": a, "to": b, "rel": rel, "label": label, **kw}


# Deliberately shuffled node order: layout must not depend on the order the agent wrote.
BUSY = {
    "vizeng": 1, "kind": "model-native", "title": "Filings pipeline internals",
    "nodes": [
        n("alert-sink", "AlertPublishSink", "Sink", "deliver"),
        n("filing-source", "EdgarFilingSource", "Source", "ingest"),
        n("config-policy", "ThresholdPolicy", "Policy", "config"),
        n("classify", "FilingClassifyTransform", "Transform", "process"),
        n("rss-source", "RssFeedSource", "Source", "ingest"),
        n("store", "FilingLedgerStore", "Store", "storage"),
        n("dedup", "FilingDedupGate", "Gate", "process"),
        n("api", "AdminApiEntry", "Entry", "admin"),
        n("normalize", "TickerNormalizeTransform", "Transform", "process"),
        n("orch", "IngestOrchestrator", "Orchestrator", "ingest"),
        n("audit-sink", "AuditLogSink", "Sink", "deliver"),
        n("router", "SeverityRouter", "Router", "process"),
        n("contract", "FilingContract", "Contract", "config"),
        n("replay", "LedgerReplayEntry", "Entry", "admin"),
        n("webhook", "WebhookAdapter", "Adapter", "deliver"),
        {"id": "note-1", "shape": "note", "label": "Should dedup move before normalize?"},
    ],
    "edges": [
        e("e1", "orch", "filing-source", "calls", "polls every 30s and hands back RawItem batches"),
        e("e2", "orch", "rss-source", "calls", "polls feeds on their own schedule"),
        e("e3", "filing-source", "dedup", "emits", "RawItem stream with source cursor attached", weight="thick"),
        e("e4", "rss-source", "dedup", "emits", "RawItem stream"),
        e("e5", "dedup", "normalize", "emits", "unique RawItem only, duplicates dropped with reason", weight="thick"),
        e("e6", "normalize", "classify", "emits", "NormalizedItem with resolved tickers"),
        e("e7", "classify", "router", "emits", "Decision"),
        e("e8", "router", "alert-sink", "emits", "high severity decisions only"),
        e("e9", "router", "audit-sink", "emits", "every decision regardless of severity"),
        e("e10", "alert-sink", "webhook", "calls", "POST with retry and idempotency key"),
        e("e11", "dedup", "store", "reads", "seen fingerprints for the last 7 days", style="dotted"),
        e("e12", "classify", "store", "writes", "decision rows keyed by item id"),
        e("e13", "config-policy", "classify", "configures", "severity thresholds per sector", style="dotted"),
        e("e14", "config-policy", "router", "configures", "routing table", style="dotted"),
        e("e15", "contract", "normalize", "implements", "NormalizedItem schema v3", style="dotted"),
        e("e16", "orch", "store", "writes", "cursor checkpoint after each batch"),
        e("e17", "api", "config-policy", "writes", "admin threshold overrides"),
        e("e18", "replay", "store", "reads", "historical items for a date range"),
        e("e19", "replay", "dedup", "calls", "re-feeds items through the pipeline"),
        e("e20", "store", "orch", "reads", "last cursor on startup"),
    ],
}

MEASURE = (Path(__file__).resolve().parent / "e2e_layout_measure.js").read_text()

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def serve(doc):
    repo = Path(tempfile.mkdtemp())
    (repo / ".git").mkdir()
    (repo / ".vizeng").mkdir()
    (repo / ".vizeng" / "d.json").write_text(json.dumps(doc))
    p = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--repo", str(repo), "--port", "0", "--name", "d"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state = repo / ".vizeng" / ".server.json"
    for _ in range(100):
        if state.exists():
            break
        time.sleep(0.05)
    return p, json.loads(state.read_text())["url"]


with sync_playwright() as pw:
    br = pw.chromium.launch()
    p, url = serve(BUSY)
    errs = []
    for scheme in ("light", "dark"):
        pg = br.new_page(viewport={"width": 1600, "height": 1000}, color_scheme=scheme)
        pg.on("pageerror", lambda ex: errs.append(str(ex)))
        pg.goto(url)
        pg.wait_for_selector("[data-node='store']")
        time.sleep(0.4)
        pg.screenshot(path=str(OUT / f"layout-{scheme}.png"))
        if scheme == "light":
            # 1:1 render of the whole diagram, to judge text the way a reader sees it
            size = pg.evaluate("""() => { const b = sceneBounds(routes()); window.vizeng.view = {k: 1, x: 40 - b.x, y: 40 - b.y};
                                          vizengRender(); return [Math.ceil(b.w) + 80, Math.ceil(b.h) + 80]; }""")
            pg.set_viewport_size({"width": size[0] + 300, "height": max(size[1] + 50, 600)})
            pg.screenshot(path=str(OUT / "layout-full.png"), clip={"x": 0, "y": 44, "width": size[0], "height": size[1]})
            m = pg.evaluate(MEASURE)
            print(json.dumps({k: v for k, v in m.items() if k != "labelWidths"}, indent=1))
            print("label widths:", sorted(m["labelWidths"]))
        pg.close()
    check("no page errors", not errs, "; ".join(errs))
    check("no edge label overlaps a shape", not m["labelOnNode"], m["labelOnNode"])
    check("no edge labels overlap each other", not m["labelOnLabel"], m["labelOnLabel"])
    check("no line (its own or another) runs through a label", not m["lineUnderLabel"], m["lineUnderLabel"])
    check("no edge passes through an unrelated shape", not m["edgeThroughNode"], m["edgeThroughNode"])
    check("few edge crossings", m["crossings"] <= 3, m["crossings"])
    check("edge labels stay compact", max(m["labelWidths"]) <= 180, max(m["labelWidths"]))
    check("same-group nodes sit closer together than average", m["groupTightness"] <= 0.75, m["groupTightness"])
    check("render stays fast enough to drag", m["renderMs"] <= 25, f"{m['renderMs']}ms")
    p.terminate()
    p.wait(10)
    br.close()

print(f"\n{sum(results)}/{len(results)} passed  (screenshots: {OUT})")
raise SystemExit(0 if all(results) else 1)
