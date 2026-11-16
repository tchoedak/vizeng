"""Browser E2E for server auto-close. Starts its own servers; needs Python Playwright.

    python3 tests/e2e_lifecycle.py [screenshot-dir]
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
DOC = {"vizeng": 1, "kind": "system", "title": "t", "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
       "edges": [{"id": "e", "from": "a", "to": "b"}]}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def serve(*args):
    repo = Path(tempfile.mkdtemp())
    (repo / ".git").mkdir()
    (repo / ".vizeng").mkdir()
    (repo / ".vizeng" / "d.json").write_text(json.dumps(DOC))
    p = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--repo", str(repo), "--port", "0", "--name", "d", *args],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    state = repo / ".vizeng" / ".server.json"
    for _ in range(100):
        if state.exists():
            break
        time.sleep(0.05)
    return p, json.loads(state.read_text())["url"], state


def wait_exit(p, timeout):
    try:
        out, _ = p.communicate(timeout=timeout)
        return True, out
    except subprocess.TimeoutExpired:
        return False, ""


with sync_playwright() as pw:
    br = pw.chromium.launch()

    # 1. An open but untouched tab must not keep the server alive.
    p, url, state = serve("--idle-minutes", "0.1")  # 6s
    pg = br.new_page(viewport={"width": 1280, "height": 800})
    pg.goto(url)
    pg.wait_for_selector("[data-node='a']")
    try:
        pg.wait_for_function("document.getElementById('bannerMsg').textContent.startsWith('Closing in')", timeout=8000)
    except Exception:  # reported by the check below
        pass
    banner = pg.locator("#bannerMsg").inner_text()
    check("countdown warns before closing", "Closing in" in banner, banner)
    pg.screenshot(path=str(OUT / "lifecycle-countdown.png"))
    exited, out = wait_exit(p, 15)
    check("abandoned open tab: server exits on idle", exited and "no activity" in out, out.strip().splitlines()[-1:])
    check("state file removed", not state.exists())
    pg.wait_for_function("window.vizeng.ended === true", timeout=10000)
    msg = pg.locator("#bannerMsg").inner_text()
    check("page shows session-ended banner", "session has closed" in msg, msg)
    pg.screenshot(path=str(OUT / "lifecycle-ended.png"))
    pg.close()

    # 2. A person actively using the page keeps it alive past the idle limit.
    p, url, state = serve("--idle-minutes", "0.1")
    pg = br.new_page(viewport={"width": 1280, "height": 800})
    pg.goto(url)
    pg.wait_for_selector("[data-node='a']")
    for _ in range(6):  # 12s of activity against a 6s idle limit
        pg.mouse.move(600, 400)
        pg.mouse.wheel(0, -1)
        time.sleep(2)
    check("active human keeps the server alive", p.poll() is None)
    check("no countdown while active", "Closing" not in pg.locator("#bannerMsg").inner_text())
    exited, _ = wait_exit(p, 15)
    check("and it still exits once they stop", exited)
    pg.close()

    # 3. Closing the tab shuts down after the grace period, well before the idle limit.
    p, url, state = serve("--idle-minutes", "10", "--bye-grace-seconds", "2")
    pg = br.new_page()
    pg.goto(url)
    pg.wait_for_selector("[data-node='a']")
    time.sleep(1.5)
    pg.close()
    t0 = time.time()
    exited, out = wait_exit(p, 15)
    check("closed tab: server exits after grace", exited and "tab closed" in out, f"{time.time() - t0:.1f}s")

    # 4. Reloading the page is not mistaken for closing it.
    p, url, state = serve("--idle-minutes", "10", "--bye-grace-seconds", "3")
    pg = br.new_page()
    pg.goto(url)
    pg.wait_for_selector("[data-node='a']")
    pg.reload()
    pg.wait_for_selector("[data-node='a']")
    time.sleep(6)
    check("reload survives", p.poll() is None)
    p.terminate()
    wait_exit(p, 10)
    br.close()

print(f"\n{sum(results)}/{len(results)} passed  (screenshots: {OUT})")
raise SystemExit(0 if all(results) else 1)
