"""End-to-end check of the editor in headless Chromium against a running server.

    VIZENG_URL=<url from vizeng serve> VIZENG_DIR=<repo>/.vizeng OUT=<dir> python3 tests/e2e_browser.py

Drives the UI the way a person would (mouse and keyboard), then checks the file on disk.
"""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

url, vdir, out = os.environ["VIZENG_URL"], Path(os.environ["VIZENG_DIR"]), Path(os.environ["OUT"])
out.mkdir(parents=True, exist_ok=True)
disk = lambda: json.loads((vdir / "internals.json").read_text())  # noqa: E731
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def wait_saved(page, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate("!window.vizeng.dirty && !window.vizeng.saving"):
            return True
        time.sleep(0.1)
    return False


with sync_playwright() as p:
    errs = []  # shared across schemes so an error in either fails the check
    for scheme in ("light", "dark"):
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme, accept_downloads=True)
        pg.on("pageerror", lambda e, s=scheme: errs.append(f"{s}: {e}"))
        pg.on("console", lambda m, s=scheme: m.type == "error" and errs.append(f"{s}: {m.text}"))
        pg.goto(url)
        pg.wait_for_selector("[data-node='pipeline']")
        time.sleep(0.5)
        pg.screenshot(path=str(out / f"01-loaded-{scheme}.png"))
        b.close()
    check("no page errors on load", not errs, "; ".join(errs))

    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_selector("[data-node='pipeline']")
    wait_saved(pg)
    n_nodes = pg.locator("[data-node]").count()
    check("all nodes render", n_nodes == 11, f"{n_nodes}")
    check("auto-layout positions persisted to disk", all("x" in n for n in disk()["nodes"]))

    def box(nid):
        return pg.locator(f"[data-node='{nid}']").first.bounding_box()

    # create a box with the tool
    pg.keyboard.press("b")
    pg.mouse.click(300, 760)
    pg.keyboard.type("RssConnectorAdapter")
    pg.keyboard.press("Escape")
    wait_saved(pg)
    labels = [n.get("label") for n in disk()["nodes"]]
    check("box tool creates a node and label typing saves to disk", "RssConnectorAdapter" in labels)
    new_id = next(n["id"] for n in disk()["nodes"] if n.get("label") == "RssConnectorAdapter")

    # connect new box -> news-source with the arrow tool
    pg.keyboard.press("a")
    a, t = box(new_id), box("news-source")
    pg.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(t["x"] + t["width"] / 2, t["y"] + t["height"] / 2, steps=8)
    pg.mouse.up()
    wait_saved(pg)
    e = [e for e in disk()["edges"] if e["from"] == new_id and e["to"] == "news-source"]
    check("arrow tool connects two shapes", len(e) == 1)
    pg.get_by_role("button", name="Dotted", exact=True).click()
    pg.get_by_role("button", name="Thick", exact=True).click()
    wait_saved(pg)
    e = [e for e in disk()["edges"] if e["from"] == new_id][0]
    check("edge set to dotted + thick", e.get("style") == "dotted" and e.get("weight") == "thick", str(e))
    pg.screenshot(path=str(out / "02-connected.png"))

    # resize via the se handle
    pg.keyboard.press("v")
    bb = box(new_id)
    pg.mouse.click(bb["x"] + 20, bb["y"] + 20)
    before = next(n for n in disk()["nodes"] if n["id"] == new_id)["w"]
    hb = pg.locator("[data-handle='se']").bounding_box()
    pg.mouse.move(hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(hb["x"] + 80, hb["y"] + 30, steps=6)
    pg.mouse.up()
    wait_saved(pg)
    after = next(n for n in disk()["nodes"] if n["id"] == new_id)["w"]
    check("resize handle widens the node", after > before, f"{before}->{after}")

    # move by drag
    bb = box("ledger")
    old = next(n for n in disk()["nodes"] if n["id"] == "ledger")
    pg.mouse.move(bb["x"] + 30, bb["y"] + 30)
    pg.mouse.down()
    pg.mouse.move(bb["x"] + 30, bb["y"] + 150, steps=6)
    pg.mouse.up()
    wait_saved(pg)
    new = next(n for n in disk()["nodes"] if n["id"] == "ledger")
    check("dragging moves a node", new["y"] > old["y"] + 50, f"{old['y']}->{new['y']}")

    # undo restores the move
    pg.keyboard.press("Meta+z")
    wait_saved(pg)
    check("undo restores previous position", next(n for n in disk()["nodes"] if n["id"] == "ledger")["y"] == old["y"])

    # zoom + fit
    k0 = pg.evaluate("window.vizeng.view.k")
    pg.mouse.move(700, 450)
    pg.mouse.wheel(0, -400)
    k1 = pg.evaluate("window.vizeng.view.k")
    check("wheel zooms in", k1 > k0, f"{k0:.2f}->{k1:.2f}")
    pg.keyboard.press("f")
    k2 = pg.evaluate("window.vizeng.view.k")
    bb = pg.evaluate("(() => { const r = document.querySelector('#svg g[transform]').getBBox(); return r; })()")
    check("fit re-centers", abs(k2 - k0) < 0.05, f"{k2:.2f}")
    pg.screenshot(path=str(out / "03-fit.png"))

    # agent writes to disk -> browser reloads
    d = disk()
    card = {"role": "Policy", "purpose": "publish thresholds"}
    d["nodes"].append({"id": "agent-added", "label": "ThresholdPolicy", "card": card})
    (vdir / "internals.json").write_text(json.dumps(d, indent=2))
    try:
        pg.wait_for_selector("[data-node='agent-added']", timeout=5000)
        check("agent disk edit appears in the browser", True)
    except Exception as ex:  # report, don't hide
        check("agent disk edit appears in the browser", False, str(ex))
    wait_saved(pg)
    added = next((n for n in disk()["nodes"] if n["id"] == "agent-added"), {})
    check("agent node gets a saved position", "x" in added)

    def overlaps(a, b):
        return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

    hits = [n["id"] for n in disk()["nodes"] if n["id"] != "agent-added" and "x" in added and overlaps(added, n)]
    check("agent-added node does not land on existing shapes", not hits, str(hits))

    # conflict: human edits while agent edits
    pg.evaluate("window.vizeng.saving = true")  # hold autosave so both edits overlap
    pg.mouse.click(5, 5)
    bb = box("ledger")
    pg.mouse.click(bb["x"] + 20, bb["y"] + 20)
    pg.locator("#fLabel").fill("LedgerStoreHuman")
    d = disk()
    d["title"] = "agent retitled"
    (vdir / "internals.json").write_text(json.dumps(d, indent=2))
    pg.evaluate("window.vizeng.saving = false")
    pg.evaluate("window.vizeng && 0")
    time.sleep(2.5)
    banner = pg.locator("#banner.show").count()
    check("concurrent edit shows a conflict banner instead of clobbering", banner == 1)
    check("disk keeps the agent edit during conflict", disk()["title"] == "agent retitled")
    pg.screenshot(path=str(out / "04-conflict.png"))
    pg.get_by_role("button", name="Keep mine", exact=True).click()
    wait_saved(pg)
    labels = [n.get("label") for n in disk()["nodes"]]
    check("keep mine writes the human edit", "LedgerStoreHuman" in labels)

    # exports
    with pg.expect_download() as dl:
        pg.get_by_role("button", name="PNG", exact=True).click()
    png = out / "export.png"
    dl.value.save_as(png)
    check("PNG export downloads a PNG", png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{png.stat().st_size} bytes")
    with pg.expect_download() as dl:
        pg.get_by_role("button", name="JSON", exact=True).click()
    js = out / "export.json"
    dl.value.save_as(js)
    check("JSON export round-trips", json.loads(js.read_text())["vizeng"] == 1)

    md = (vdir / "internals.model.md").read_text()
    check("model view regenerated with human edit", "LedgerStoreHuman" in md)
    check("no page errors during interaction", not errs, "; ".join(errs))
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
