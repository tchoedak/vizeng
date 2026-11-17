"""Tests for scripts/vizeng.py. Stdlib only: python3 -m unittest discover tests"""

import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/vizeng/skills/architecture/scripts/vizeng.py"
spec = importlib.util.spec_from_file_location("vizeng", SCRIPT)
vz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vz)


def mn_doc():
    return {
        "vizeng": 1, "kind": "model-native", "title": "T",
        "nodes": [
            {"id": "a", "label": "FilingSource", "card": {"role": "Source", "purpose": "pull filings", "effects": ["HTTP"]}},
            {"id": "b", "label": "DedupGate", "card": {"role": "Gate", "never": ["write"]}},
            {"id": "n1", "shape": "note", "label": "rename b?"},
        ],
        "edges": [{"id": "e1", "from": "a", "to": "b", "rel": "emits", "label": "RawItem", "style": "dotted"}],
    }


class ValidateTests(unittest.TestCase):
    def test_a_valid_document_has_no_problems(self):
        self.assertEqual(vz.validate(mn_doc()), [])

    def test_a_dangling_edge_is_reported_rather_than_silently_not_drawn(self):
        d = mn_doc()
        d["edges"][0]["to"] = "ghost"
        self.assertTrue(any("unknown node 'ghost'" in p for p in vz.validate(d)))

    def test_duplicate_node_ids_are_reported(self):
        d = mn_doc()
        d["nodes"][1]["id"] = "a"
        self.assertTrue(any("duplicate node id" in p for p in vz.validate(d)))

    def test_model_native_boxes_need_a_role_from_the_closed_vocabulary_as_a_warning(self):
        d = mn_doc()
        d["nodes"][0]["card"]["role"] = "Manager"
        self.assertTrue(any("card.role" in p for p in vz.lint(d)))
        self.assertEqual(vz.validate(d), [])

    def test_notes_do_not_need_a_role(self):
        self.assertEqual(vz.lint(mn_doc()), [])

    def test_a_sentence_on_an_edge_is_a_warning_not_an_error(self):
        d = mn_doc()
        d["edges"][0]["label"] = "RawItem batches pulled every 30 seconds from the feed"
        self.assertEqual(vz.validate(d), [])
        self.assertTrue(any("edge 'e1': label is" in p for p in vz.lint(d)))

    def test_an_edge_label_at_the_limit_is_fine(self):
        d = mn_doc()
        d["edges"][0]["label"] = "x" * vz.EDGE_LABEL_MAX
        self.assertEqual(vz.lint(d), [])

    def test_group_must_be_a_string(self):
        d = mn_doc()
        d["nodes"][0]["group"] = ["ingest"]
        self.assertTrue(any("group must be a string" in p for p in vz.validate(d)))


class ModelViewTests(unittest.TestCase):
    def test_model_view_folds_edges_into_cards_and_drops_geometry(self):
        d = mn_doc()
        d["nodes"][0].update(x=10, y=20, w=200, h=90)
        md = vz.model_view(d)
        self.assertIn("## FilingSource [Source]", md)
        self.assertIn("-> emits DedupGate (RawItem) [weak]", md)
        self.assertIn("effects: HTTP", md)
        self.assertNotIn("200", md)

    def test_group_is_part_of_the_model_view(self):
        d = mn_doc()
        d["nodes"][0]["group"] = "ingest"
        self.assertIn("## FilingSource [Source]\ngroup: ingest\n", vz.model_view(d))

    def test_notes_are_listed_as_open_comments_not_abstractions(self):
        md = vz.model_view(mn_doc())
        self.assertIn("## Open notes", md)
        self.assertIn("- rename b?", md)
        self.assertNotIn("## rename b?", md)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vdir = Path(self.tmp.name) / ".vizeng"
        vz.ensure_dir(self.vdir)
        vz.Handler.vdir = self.vdir
        vz.Handler.token = "tok"
        vz.Handler.session = vz.Session(self.vdir, idle_s=600)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), vz.Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_api_calls_without_the_token_are_refused(self):
        self.assertEqual(self.call("GET", "/api/list")[0], 403)
        self.assertEqual(self.call("GET", "/api/list?token=wrong")[0], 403)

    def test_names_that_could_escape_the_vizeng_dir_are_rejected(self):
        self.assertEqual(self.call("GET", "/api/doc?token=tok&name=../etc")[0], 400)

    def test_save_writes_json_and_model_view(self):
        code, body = self.call("PUT", "/api/doc?token=tok&name=internals", {"doc": mn_doc(), "baseRev": ""})
        self.assertEqual(code, 200)
        self.assertTrue((self.vdir / "internals.json").exists())
        self.assertIn("FilingSource", (self.vdir / "internals.model.md").read_text())
        self.assertEqual(body["rev"], vz.rev_of(self.vdir / "internals.json"))

    def test_a_save_from_a_stale_revision_conflicts_instead_of_clobbering_the_agent(self):
        _, body = self.call("PUT", "/api/doc?token=tok&name=d", {"doc": mn_doc(), "baseRev": ""})
        agent = mn_doc()
        agent["title"] = "agent edit"
        (self.vdir / "d.json").write_text(json.dumps(agent))
        code, _ = self.call("PUT", "/api/doc?token=tok&name=d", {"doc": mn_doc(), "baseRev": body["rev"]})
        self.assertEqual(code, 409)
        self.assertEqual(json.loads((self.vdir / "d.json").read_text())["title"], "agent edit")

    def test_warnings_are_returned_but_never_block_a_save(self):
        d = mn_doc()
        d["edges"][0]["label"] = "RawItem batches pulled every 30 seconds from the feed"
        code, body = self.call("PUT", "/api/doc?token=tok&name=d", {"doc": d, "baseRev": ""})
        self.assertEqual(code, 200)
        self.assertTrue(any("label is" in p for p in body["problems"]))
        code, body = self.call("GET", "/api/doc?token=tok&name=d")
        self.assertEqual(code, 200)
        self.assertTrue(any("label is" in p for p in body["problems"]))

    def test_structurally_invalid_documents_are_not_saved(self):
        d = mn_doc()
        d["edges"][0]["from"] = "ghost"
        code, body = self.call("PUT", "/api/doc?token=tok&name=d", {"doc": d, "baseRev": ""})
        self.assertEqual(code, 422)
        self.assertFalse((self.vdir / "d.json").exists())

    def test_broken_json_written_by_an_agent_is_surfaced_not_masked(self):
        (self.vdir / "bad.json").write_text("{nope")
        code, body = self.call("GET", "/api/doc?token=tok&name=bad")
        self.assertEqual(code, 422)
        self.assertIn("not valid JSON", body["error"])

    def test_a_direct_agent_write_regenerates_the_stale_model_view_on_load(self):
        self.call("PUT", "/api/doc?token=tok&name=d", {"doc": mn_doc(), "baseRev": ""})
        time.sleep(0.02)
        agent = mn_doc()
        agent["nodes"][0]["label"] = "EdgarFilingSource"
        (self.vdir / "d.json").write_text(json.dumps(agent))
        self.call("GET", "/api/doc?token=tok&name=d")
        self.assertIn("EdgarFilingSource", (self.vdir / "d.model.md").read_text())

    def test_the_rev_endpoint_tracks_disk_changes(self):
        self.call("PUT", "/api/doc?token=tok&name=d", {"doc": mn_doc(), "baseRev": ""})
        _, a = self.call("GET", "/api/rev?token=tok&name=d")
        (self.vdir / "d.json").write_text(json.dumps({**mn_doc(), "title": "x"}))
        _, b = self.call("GET", "/api/rev?token=tok&name=d")
        self.assertNotEqual(a["rev"], b["rev"])


class SessionLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vdir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_idle_session_asks_to_shut_down(self):
        s = vz.Session(self.vdir, idle_s=0.2)
        self.assertIsNone(s.check())
        time.sleep(0.3)
        self.assertIn("no activity", s.check())

    def test_polling_alone_does_not_keep_an_abandoned_tab_alive(self):
        s = vz.Session(self.vdir, idle_s=0.3)
        for _ in range(4):
            s.heartbeat("tab")
            s.touch(ago_s=999)  # page reports the human last interacted long ago
            time.sleep(0.1)
        self.assertIsNotNone(s.check())

    def test_human_interaction_extends_the_session(self):
        s = vz.Session(self.vdir, idle_s=0.3)
        for _ in range(5):
            s.heartbeat("tab")
            s.touch(ago_s=0)
            time.sleep(0.1)
        self.assertIsNone(s.check())

    def test_an_agent_write_counts_as_activity(self):
        s = vz.Session(self.vdir, idle_s=0.3)
        time.sleep(0.2)
        (self.vdir / "internals.json").write_text("{}")
        self.assertIsNone(s.check())
        time.sleep(0.2)
        self.assertIsNone(s.check(), "the write 0.2s ago should have reset the 0.3s idle clock")

    def test_closing_the_last_tab_shuts_down_after_the_grace_period(self):
        s = vz.Session(self.vdir, idle_s=600, grace_s=0.2)
        s.heartbeat("tab")
        s.bye("tab")
        self.assertIsNone(s.check())
        time.sleep(0.3)
        self.assertEqual(s.check(), "browser tab closed")

    def test_a_reload_within_the_grace_period_survives(self):
        s = vz.Session(self.vdir, idle_s=600, grace_s=0.3)
        s.heartbeat("old")
        s.bye("old")
        time.sleep(0.1)
        s.heartbeat("new")
        time.sleep(0.3)
        self.assertIsNone(s.check())

    def test_a_tab_that_goes_silent_counts_as_closed(self):
        s = vz.Session(self.vdir, idle_s=600, grace_s=0.1, silent_s=0.1)
        s.heartbeat("tab")
        time.sleep(0.15)
        self.assertIsNone(s.check())  # dropped now; grace starts
        time.sleep(0.15)
        self.assertEqual(s.check(), "browser tab closed")

    def test_never_opening_the_url_still_hits_the_idle_rule_not_the_tab_rule(self):
        s = vz.Session(self.vdir, idle_s=600, grace_s=0.01)
        time.sleep(0.05)
        self.assertIsNone(s.check())

    def test_idle_minutes_zero_never_closes_on_idle(self):
        s = vz.Session(self.vdir, idle_s=0)
        time.sleep(0.05)
        self.assertIsNone(s.check())
        self.assertIsNone(s.idle_left())


class ServeProcessTests(unittest.TestCase):
    """The real `serve` process, not just the Session object."""

    def _start(self, repo, *extra):
        import subprocess
        p = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--repo", repo, "--port", "0", *extra],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        state = Path(repo) / ".vizeng" / ".server.json"
        for _ in range(100):
            if state.exists():
                break
            time.sleep(0.05)
        return p, state

    def test_an_idle_server_exits_on_its_own_and_removes_its_state_file(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            p, state = self._start(t, "--idle-minutes", "0.03")  # ~2s
            self.assertTrue(state.exists())
            out, _ = p.communicate(timeout=15)
            self.assertEqual(p.returncode, 0)
            self.assertIn("shutting down (no activity", out)
            self.assertFalse(state.exists())

    def test_sigterm_exits_cleanly_and_removes_the_state_file(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            p, state = self._start(t)
            p.terminate()
            p.communicate(timeout=10)
            self.assertEqual(p.returncode, 0)
            self.assertFalse(state.exists())


class CliTests(unittest.TestCase):
    def test_render_fails_on_structural_problems(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            v = Path(t) / ".vizeng"
            v.mkdir()
            d = mn_doc()
            d["edges"][0]["to"] = "ghost"
            (v / "x.json").write_text(json.dumps(d))
            self.assertEqual(vz.main(["render", "--repo", t]), 1)
            self.assertFalse((v / "x.model.md").exists())

    def test_render_writes_the_model_view_despite_warnings(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            v = Path(t) / ".vizeng"
            v.mkdir()
            d = mn_doc()
            d["edges"][0]["label"] = "a whole sentence explaining what happens on this edge"
            (v / "x.json").write_text(json.dumps(d))
            self.assertEqual(vz.main(["render", "--repo", t]), 0)
            self.assertTrue((v / "x.model.md").exists())

    def test_render_ignores_the_server_state_file(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            v = Path(t) / ".vizeng"
            v.mkdir()
            (v / ".server.json").write_text('{"url": "x", "pid": 1}')
            (v / "x.json").write_text(json.dumps(mn_doc()))
            self.assertEqual(vz.main(["render", "--repo", t]), 0)

    def test_init_creates_doc_at_repo_root_from_a_subdirectory(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            sub = Path(t) / "a" / "b"
            sub.mkdir(parents=True)
            self.assertEqual(vz.main(["init", "internals", "--kind", "model-native", "--repo", str(sub)]), 0)
            self.assertTrue((Path(t) / ".vizeng" / "internals.json").exists())
            self.assertIn(".server.json", (Path(t) / ".vizeng" / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
