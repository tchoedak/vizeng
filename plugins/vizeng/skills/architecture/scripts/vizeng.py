#!/usr/bin/env python3
"""vizeng: local diagram server and model-view renderer for the vizeng:architecture skill.

Why a server and not a static HTML file:
  The diagram is a shared surface between a human and an agent. The agent edits
  `.vizeng/*.json` on disk; the human edits in the browser. A static page cannot
  write back to the repo, and a page that can only download files forces the
  human to shuttle JSON by hand. The server is the smallest thing that lets both
  sides write the same file: the browser polls the file revision, reloads when
  the agent changes it, and saves with optimistic concurrency (409 on a stale
  revision) so neither side silently clobbers the other.

Why every save also writes `<name>.model.md`:
  The JSON carries geometry (x, y, w, h, colors) that is pure noise to a model.
  The `.model.md` file is the same design with geometry stripped and edges
  folded into each abstraction's card. It is the file agents should read; the
  JSON is the file the editor reads. Never hand-edit the `.model.md` - it is
  regenerated on every save and by `vizeng.py render`.

Security: binds 127.0.0.1 only and requires a per-process random token on
every /api call, so another web page in the same browser cannot read or write
the repo through this server (a localhost CSRF). Names are restricted to
[a-z0-9-] so a request cannot escape `.vizeng/`.

Lifetime: the server shuts itself down rather than relying on anyone to stop it.
Agents start it in the background and humans rarely say "I'm done", so a server
that waits to be told leaks a process per session. Two rules, checked every
couple of seconds by a watchdog thread (see Session):
  - idle: no human interaction in the page and no agent write to .vizeng/*.json
    for --idle-minutes (default 10). Background polling is NOT activity - an
    abandoned open tab polls forever and must not keep the server alive.
  - tab closed: every page that connected has said goodbye (pagehide beacon)
    or gone silent, and nothing happened for BYE_GRACE_S. A reload says
    goodbye and reconnects within the grace window, so it survives.
The page shows a countdown in the last minute and a "session ended" banner after.

Stdlib only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SKILL_DIR = Path(__file__).resolve().parent.parent
APP_HTML = SKILL_DIR / "assets" / "app.html"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
KINDS = ("system", "model-native")
SHAPES = ("box", "circle", "text", "note")
# Keep in step with references/model-native.md. Embedded into every .model.md so the
# file is self-contained for an agent that has never seen this skill.
ROLE_CONTRACTS = {
    "Entry": "process boundary; parses, validates, delegates; no domain logic",
    "Source": "produces items from outside; owns its cursor; no filtering",
    "Gate": "pure keep/drop decision with a reason; no effects",
    "Transform": "pure, deterministic input -> output; no effects",
    "Router": "chooses a destination; never modifies the item",
    "Orchestrator": "sequences others, owns cross-role control flow; no domain rules",
    "Store": "sole owner of one aggregate's persistence",
    "Adapter": "sole wrapper of one external system; translates its errors/types",
    "Policy": "rules/thresholds as data or pure functions; no effects",
    "Sink": "terminal output; owns delivery semantics",
    "Contract": "shared data types across boundaries; no behavior",
}
ROLES = tuple(ROLE_CONTRACTS)
CARD_ORDER = (
    "role", "purpose", "owns", "does", "never", "in", "out",
    "effects", "fails", "invariants", "paths", "tests", "notes",
)


# ---------------------------------------------------------------- documents

def blank_doc(kind: str, title: str) -> dict:
    return {"vizeng": 1, "kind": kind, "title": title, "nodes": [], "edges": []}


def validate(doc: object) -> list[str]:
    """Return a list of problems. Empty list means the document is usable.

    Strict on structure (ids, references, enums) because a dangling edge or a
    duplicate id renders as a silently missing arrow. Lenient on card content
    because cards are prose the agent and human are still negotiating.
    """
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a JSON object"]
    if doc.get("vizeng") != 1:
        errs.append("missing or unsupported 'vizeng' version (expected 1)")
    if doc.get("kind") not in KINDS:
        errs.append(f"'kind' must be one of {KINDS}")
    nodes = doc.get("nodes")
    edges = doc.get("edges")
    if not isinstance(nodes, list):
        return errs + ["'nodes' must be a list"]
    if not isinstance(edges, list):
        return errs + ["'edges' must be a list"]
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"]:
            errs.append(f"nodes[{i}] needs a string 'id'")
            continue
        if n["id"] in ids:
            errs.append(f"duplicate node id {n['id']!r}")
        ids.add(n["id"])
        if n.get("shape", "box") not in SHAPES:
            errs.append(f"node {n['id']!r}: shape must be one of {SHAPES}")
        if "group" in n and not isinstance(n["group"], str):
            errs.append(f"node {n['id']!r}: group must be a string")
    eids: set[str] = set()
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            errs.append(f"edges[{i}] is not an object")
            continue
        eid = e.get("id", f"#{i}")
        if eid in eids:
            errs.append(f"duplicate edge id {eid!r}")
        eids.add(eid)
        for end in ("from", "to"):
            if e.get(end) not in ids:
                errs.append(f"edge {eid!r}: '{end}' references unknown node {e.get(end)!r}")
        if e.get("style", "solid") not in ("solid", "dotted"):
            errs.append(f"edge {eid!r}: style must be solid|dotted")
        if e.get("weight", "normal") not in ("normal", "thick"):
            errs.append(f"edge {eid!r}: weight must be normal|thick")
        if e.get("arrow", "end") not in ("end", "none", "both"):
            errs.append(f"edge {eid!r}: arrow must be end|none|both")
    return errs


# Two wrapped lines in the editor hold about this much; longer labels get cut with an ellipsis.
EDGE_LABEL_MAX = 40


def lint(doc: dict) -> list[str]:
    """Advisory problems in a structurally valid document. They never block a save.

    The diagram still works, but reads worse: a missing role leaves a component without a
    contract, and a sentence on an arrow is cut short on the canvas and crowds its neighbors.
    """
    warns: list[str] = []
    for n in doc.get("nodes", []):
        role = (n.get("card") or {}).get("role")
        if doc.get("kind") == "model-native" and n.get("shape", "box") in ("box", "circle") and role not in ROLES:
            warns.append(f"node {n['id']!r}: card.role must be one of {ROLES} (got {role!r})")
    for e in doc.get("edges", []):
        label = e.get("label") or ""
        if len(label) > EDGE_LABEL_MAX:
            warns.append(
                f"edge {e.get('id')!r}: label is {len(label)} chars (max {EDGE_LABEL_MAX}); name what flows"
                " (a type or short verb phrase) and move the detail into the card or a note"
            )
    return warns


def _fmt(v: object) -> str:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v)


def model_view(doc: dict) -> str:
    """Render the geometry-free, model-oriented text view of a document."""
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    out_edges: dict[str, list[dict]] = {}
    in_edges: dict[str, list[dict]] = {}
    for e in doc.get("edges", []):
        out_edges.setdefault(e["from"], []).append(e)
        in_edges.setdefault(e["to"], []).append(e)

    def name(nid: str) -> str:
        n = nodes.get(nid, {})
        return n.get("label") or nid

    lines = [
        f"<!-- generated by vizeng from {doc.get('_source', 'the .json sibling')}; do not edit -->",
        f"# {doc.get('title', 'Untitled')} [{doc.get('kind')}]",
    ]
    if doc.get("summary"):
        lines.append(doc["summary"])
    tech = doc.get("technique")
    if isinstance(tech, dict) and tech:
        lines.append(f"technique: {tech.get('name', '')} - {tech.get('why', '')}".rstrip(" -"))
    if doc.get("kind") == "model-native":
        used = sorted({(n.get("card") or {}).get("role") for n in nodes.values()} - {None})
        if used:
            lines.append("role contracts (a card states only deviations):")
            lines.extend(f"- {r}: {ROLE_CONTRACTS.get(r, '?')}" for r in used)
    lines.append("")

    notes = []
    for nid, n in nodes.items():
        shape = n.get("shape", "box")
        if shape in ("text", "note"):
            if shape == "note" and n.get("label"):
                notes.append(n["label"])
            continue
        card = n.get("card") or {}
        head = f"## {name(nid)}"
        if card.get("role"):
            head += f" [{card['role']}]"
        if n.get("status") == "proposed":
            head += " (proposed)"
        lines.append(head)
        if n.get("group"):
            lines.append(f"group: {n['group']}")
        for key in CARD_ORDER:
            if key == "role" or key not in card or card[key] in ("", [], None):
                continue
            lines.append(f"{key}: {_fmt(card[key])}")
        for key in sorted(set(card) - set(CARD_ORDER)):
            if card[key] not in ("", [], None):
                lines.append(f"{key}: {_fmt(card[key])}")
        for e in out_edges.get(nid, []):
            rel = e.get("rel") or e.get("label") or "->"
            extra = f" ({e['label']})" if e.get("label") and e.get("rel") else ""
            dash = " [weak]" if e.get("style") == "dotted" else ""
            lines.append(f"-> {rel} {name(e['to'])}{extra}{dash}")
        for e in in_edges.get(nid, []):
            if e.get("arrow") == "both":
                rel = e.get("rel") or e.get("label") or "<->"
                lines.append(f"<- {rel} {name(e['from'])}")
        lines.append("")
    if notes:
        lines.append("## Open notes (human comments to address)")
        lines.extend(f"- {t}" for t in notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def rev_of(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def ensure_dir(vdir: Path) -> None:
    vdir.mkdir(parents=True, exist_ok=True)
    gi = vdir / ".gitignore"
    if not gi.exists():
        gi.write_text(".server.json\n.tmp-*\n")


def write_doc(vdir: Path, name: str, doc: dict) -> str:
    """Write <name>.json and its <name>.model.md. Returns the new revision."""
    ensure_dir(vdir)
    jpath = vdir / f"{name}.json"
    clean = {k: v for k, v in doc.items() if not k.startswith("_")}
    atomic_write(jpath, json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
    atomic_write(vdir / f"{name}.model.md", model_view({**clean, "_source": jpath.name}))
    return rev_of(jpath)


def find_vizeng_dir(start: Path) -> Path:
    """`.vizeng/` lives at the repo root: nearest ancestor with .git, else start."""
    start = start.resolve()
    for p in (start, *start.parents):
        if (p / ".git").exists():
            return p / ".vizeng"
    return start / ".vizeng"


# ------------------------------------------------------------------- server

BYE_GRACE_S = 60.0      # tab closed -> exit after this long with no activity
CLIENT_SILENT_S = 180.0  # a page this quiet is gone (crash, sleep); hidden tabs still poll ~1/min


class Session:
    """Decides when the server should exit. All times are time.monotonic()."""

    def __init__(self, vdir: Path, idle_s: float, grace_s: float = BYE_GRACE_S,
                 silent_s: float = CLIENT_SILENT_S):
        self.vdir, self.idle_s, self.grace_s, self.silent_s = vdir, idle_s, grace_s, silent_s
        self.lock = threading.Lock()
        self.last = time.monotonic()
        self.clients: dict[str, float] = {}
        self.ever_connected = False
        self.empty_since: float | None = None
        self.disk_mtime = self._mtime()

    def _mtime(self) -> float:
        ms = [p.stat().st_mtime for p in self.vdir.glob("*.json") if NAME_RE.match(p.stem)]
        return max(ms, default=0.0)

    def touch(self, ago_s: float = 0.0) -> None:
        with self.lock:
            self.last = max(self.last, time.monotonic() - max(0.0, ago_s))

    def heartbeat(self, client: str) -> None:
        if not client:
            return
        with self.lock:
            self.clients[client[:64]] = time.monotonic()
            self.ever_connected = True
            self.empty_since = None

    def bye(self, client: str) -> None:
        with self.lock:
            self.clients.pop(client[:64], None)
            if self.ever_connected and not self.clients and self.empty_since is None:
                self.empty_since = time.monotonic()

    def idle_left(self) -> float | None:
        if not self.idle_s:
            return None
        return max(0.0, self.idle_s - (time.monotonic() - self.last))

    def check(self) -> str | None:
        """Return a shutdown reason, or None to keep running."""
        m = self._mtime()
        if m > self.disk_mtime:  # the agent (or anyone) wrote a diagram: that is activity
            self.disk_mtime = m
            self.touch()
        now = time.monotonic()
        with self.lock:
            for cid, seen in list(self.clients.items()):
                if now - seen > self.silent_s:
                    del self.clients[cid]
            if self.ever_connected and not self.clients and self.empty_since is None:
                self.empty_since = now
            if self.idle_s and now - self.last > self.idle_s:
                return f"no activity for {self.idle_s / 60:g} min"
            if (self.empty_since is not None and now - self.empty_since > self.grace_s
                    and now - self.last > self.grace_s):
                return "browser tab closed"
        return None


def watchdog(srv, session: Session, every_s: float = 2.0) -> None:
    while True:
        time.sleep(every_s)
        reason = session.check()
        if reason:
            print(f"vizeng: shutting down ({reason})", flush=True)
            srv.shutdown()
            return


class Handler(BaseHTTPRequestHandler):
    vdir: Path
    token: str
    session: Session
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # quiet: the agent tails stdout for the URL only
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: object) -> None:
        self._send(code, json.dumps(obj).encode())

    def _authorized(self, q: dict) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False  # DNS-rebinding guard
        return secrets.compare_digest(q.get("token", [""])[0], self.token)

    def _name(self, q: dict) -> str | None:
        n = q.get("name", [""])[0]
        return n if NAME_RE.match(n) else None

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, APP_HTML.read_bytes(), "text/html; charset=utf-8")
        if not self._authorized(q):
            return self._json(403, {"error": "bad token"})
        if u.path != "/api/rev":
            self.session.touch()  # opening/switching diagrams is a human action; polling is not
        if u.path == "/api/list":
            items = []
            for p in sorted(self.vdir.glob("*.json")):
                if NAME_RE.match(p.stem):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                        items.append({"name": p.stem, "kind": d.get("kind"), "title": d.get("title")})
                    except (OSError, ValueError):
                        items.append({"name": p.stem, "kind": None, "title": "(unreadable JSON)"})
            return self._json(200, {"diagrams": items, "dir": str(self.vdir)})
        name = self._name(q)
        if u.path == "/api/rev":
            # The poll doubles as heartbeat; `ago` is seconds since the human last
            # interacted with the page, so only real interaction extends the session.
            # Works without a diagram name so an empty workspace still heartbeats.
            self.session.heartbeat(q.get("client", [""])[0])
            try:
                self.session.touch(float(q["ago"][0]))
            except (KeyError, ValueError):
                pass
            rev = rev_of(self.vdir / f"{name}.json") if name else ""
            return self._json(200, {"rev": rev, "idle_left": self.session.idle_left(), "idle_total": self.session.idle_s})
        if name is None:
            return self._json(400, {"error": "name must match [a-z0-9-]"})
        path = self.vdir / f"{name}.json"
        if u.path == "/api/doc":
            if not path.exists():
                return self._json(404, {"error": f"{path.name} not found"})
            raw = path.read_text(encoding="utf-8")
            try:
                doc = json.loads(raw)
            except ValueError as ex:
                # Surface, never mask: an agent wrote broken JSON and the human must see it.
                return self._json(422, {"error": f"{path.name} is not valid JSON: {ex}", "rev": rev_of(path)})
            structural = validate(doc)
            problems = structural + (lint(doc) if not structural else [])
            md = self.vdir / f"{name}.model.md"
            # An agent that wrote the JSON directly bypassed write_doc; keep the model view in step.
            if not structural and (not md.exists() or md.stat().st_mtime < path.stat().st_mtime):
                atomic_write(md, model_view({**doc, "_source": path.name}))
            return self._json(200, {"doc": doc, "rev": rev_of(path), "problems": problems})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        """Only /api/bye: navigator.sendBeacon from the page's pagehide handler."""
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path != "/api/bye" or not self._authorized(q):
            return self._json(403, {"error": "bad request"})
        self.session.bye(q.get("client", [""])[0])
        return self._json(200, {})

    def do_PUT(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authorized(q):
            return self._json(403, {"error": "bad token"})
        self.session.touch()
        name = self._name(q)
        if u.path != "/api/doc" or name is None:
            return self._json(400, {"error": "bad request"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            doc, base = body["doc"], body.get("baseRev", "")
        except (ValueError, KeyError) as ex:
            return self._json(400, {"error": f"bad body: {ex}"})
        structural = validate(doc)
        if structural:
            return self._json(422, {"error": "invalid document", "problems": structural})
        path = self.vdir / f"{name}.json"
        with self.lock:
            current = rev_of(path)
            if current and base != current:
                return self._json(HTTPStatus.CONFLICT, {"error": "file changed on disk", "rev": current})
            rev = write_doc(self.vdir, name, doc)
        return self._json(200, {"rev": rev, "problems": lint(doc)})


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


# ---------------------------------------------------------------------- cli

def cmd_init(a) -> int:
    vdir = find_vizeng_dir(Path(a.repo))
    if not NAME_RE.match(a.name):
        print(f"error: name {a.name!r} must match [a-z0-9-]", file=sys.stderr)
        return 2
    path = vdir / f"{a.name}.json"
    if path.exists():
        print(f"exists: {path}")
        return 0
    write_doc(vdir, a.name, blank_doc(a.kind, a.title or a.name))
    print(f"created: {path}")
    return 0


def cmd_render(a) -> int:
    vdir = find_vizeng_dir(Path(a.repo))
    # NAME_RE excludes dotfiles such as .server.json, which glob("*.json") would include.
    names = [a.name] if a.name else [p.stem for p in sorted(vdir.glob("*.json")) if NAME_RE.match(p.stem)]
    rc = 0
    for n in names:
        p = vdir / f"{n}.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            print(f"FAIL {p}: {ex}", file=sys.stderr)
            rc = 1
            continue
        errors = validate(doc)
        for prob in errors:
            print(f"FAIL {p.name}: {prob}", file=sys.stderr)
        if errors:
            rc = 1
            continue
        for prob in lint(doc):
            print(f"WARN {p.name}: {prob}", file=sys.stderr)
        atomic_write(vdir / f"{n}.model.md", model_view({**doc, "_source": p.name}))
        print(f"ok   {p.name} -> {n}.model.md")
    return rc


def cmd_serve(a) -> int:
    vdir = find_vizeng_dir(Path(a.repo))
    ensure_dir(vdir)
    Handler.vdir = vdir
    Handler.token = secrets.token_urlsafe(16)
    Handler.session = Session(vdir, idle_s=a.idle_minutes * 60, grace_s=a.bye_grace_seconds)
    port = free_port(a.port)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/?token={Handler.token}"
    if a.name:
        url += f"&name={a.name}"
    state = vdir / ".server.json"
    state.write_text(json.dumps({"url": url, "pid": os.getpid()}) + "\n")

    def on_term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    threading.Thread(target=watchdog, args=(srv, Handler.session), daemon=True).start()
    print(f"vizeng serving {vdir}", flush=True)
    idle = f"{a.idle_minutes:g} min idle" if a.idle_minutes else "never on idle"
    print(f"auto-close: {idle}, or {a.bye_grace_seconds:g}s after the tab closes", flush=True)
    print(f"URL {url}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("vizeng: stopped", flush=True)
    finally:
        srv.server_close()
        try:  # only remove our own state file; a newer server may have replaced it
            if json.loads(state.read_text()).get("pid") == os.getpid():
                state.unlink()
        except (OSError, ValueError):
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vizeng")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve the editor for <repo>/.vizeng")
    s.add_argument("--repo", default=".")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--name", help="diagram to open first")
    s.add_argument("--idle-minutes", type=float, default=10.0,
                   help="exit after this long without human or agent activity (0 = never)")
    s.add_argument("--bye-grace-seconds", type=float, default=BYE_GRACE_S, help=argparse.SUPPRESS)  # tests
    s.set_defaults(fn=cmd_serve)
    i = sub.add_parser("init", help="create an empty diagram")
    i.add_argument("name")
    i.add_argument("--kind", choices=KINDS, required=True)
    i.add_argument("--title")
    i.add_argument("--repo", default=".")
    i.set_defaults(fn=cmd_init)
    r = sub.add_parser("render", help="validate and regenerate .model.md files")
    r.add_argument("name", nargs="?")
    r.add_argument("--repo", default=".")
    r.set_defaults(fn=cmd_render)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
