from contextlib import closing

from creeperman.source_frontier import Frontier
from creeperman.source_pages import PageFrontier, SCHEMA


BASE = "https://library.example.org/catalog/"


def init_pages(frontier, *seeds):
    pages = PageFrontier(frontier)
    pages.init({"schema": SCHEMA, "scopes": [{
        "host": "library.example.org", "paths": ["/catalog"], "family": "directory",
        "allow_query": True, "seeds": [BASE + path for path in seeds],
    }]})
    return pages


def offline(*args):
    raise AssertionError("Unexpected network access or throttling")


def test_preexisting_import_reused_before_requests_and_after_restart(tmp_path):
    db = tmp_path / "ledger.sqlite"
    with closing(Frontier(db)) as frontier, frontier.db:
        raw = (b'<base href="/catalog/issues/"><a href="1999">directory 1999</a>'
               b'<a href="/outside">outside scope</a><a href="source.gz">download</a>')
        doc = frontier.import_document_bytes(
            raw, "html", "https://Library.Example.Org:443/catalog/#version", "paper")
        frontier.import_document_bytes(b"stored child", "html", BASE + "issues/1999", "paper")
    with closing(Frontier(db)) as frontier:
        pages = init_pages(frontier, "")
        before = frontier.db.execute("SELECT count(*) FROM observations").fetchone()[0]
        report = pages.run(1, 3, 2, 2, "test-agent", offline, offline, max_local_pages=1)
        assert report["reused_local_this_run"] == 1
        assert report["attempted_this_run"] == 0 and report["request_kinds"] == {}
        assert report["page_states"] == {"reused_local": 1, "queued": 1}
        assert frontier.db.execute("SELECT document_id FROM page_tasks WHERE url=?", (BASE,)).fetchone()[0] == doc
        assert {r[0] for r in frontier.db.execute("SELECT url FROM page_tasks")} == {BASE, BASE + "issues/1999"}
    with closing(Frontier(db)) as frontier:
        pages = init_pages(frontier, "")
        assert pages.reuse_local()["page_states"] == {"reused_local": 2}
        report = pages.run(1, 3, 2, 2, "test-agent", offline, offline)
        assert report["reused_local_this_run"] == report["attempted_this_run"] == 0
        assert frontier.db.execute("SELECT count(*) FROM observations").fetchone()[0] == before


def test_uncertain_variants_remain_in_queue(tmp_path):
    with closing(Frontier(tmp_path / "ledger.sqlite")) as frontier:
        pages = init_pages(frontier, "issue?series=A", "case", "two", "fmt", "same", "slash/", "missing")
        with frontier.db:
            for path, raw in [
                ("issue?series=B", b"other query"), ("CASE", b"other path case"),
                ("two", b"old"), ("two#new", b"new"), ("slash", b"no trailing slash"),
                ("same", b"same"), ("same#part", b"same"),
            ]:
                frontier.import_document_bytes(raw, "html", BASE + path, "archive")
            frontier.import_document_bytes(b"converted", "text", BASE + "fmt", "archive")
            lost = frontier.import_document_bytes(b"lost", "html", BASE + "missing", "archive")
            frontier.db.execute("DELETE FROM bodies WHERE sha=(SELECT sha FROM documents WHERE id=?)", (lost,))
        report = pages.reuse_local()
        assert report["reused_local_this_run"] == 1 and report["page_states"] == {"queued": 6, "reused_local": 1}
        assert frontier.db.execute("SELECT url FROM page_tasks WHERE state='reused_local'").fetchone()[0] == BASE + "same"


def test_new_version_reopens_a_previously_reused_snapshot(tmp_path):
    with closing(Frontier(tmp_path / "ledger.sqlite")) as frontier:
        pages = init_pages(frontier, "seed")
        url = BASE + "seed"
        body = b'<a href="first">index</a>'
        with frontier.db:
            original = frontier.import_document_bytes(body, "html", url, "original")
        assert pages.reuse_local(max_depth=0)["reused_local_this_run"] == 1
        with frontier.db:
            frontier.import_document_bytes(body, "html", url + "#same", "same copy")
        report = pages.run(1, 3, 0, 2, "test-agent", offline, offline)
        assert report["attempted_this_run"] == report["reused_local_this_run"] == 0
        with frontier.db:
            newer = frontier.import_document_bytes(b"updated directory", "html", url, "later")
        assert newer != original
        report = pages.reuse_local(max_depth=0)
        assert report["page_states"] == {"queued": 2} and report["attempted_this_run"] == 0
        assert frontier.db.execute("SELECT document_id FROM page_tasks WHERE url=?", (url,)).fetchone()[0] is None
        edges = set(map(tuple, frontier.db.execute("SELECT * FROM page_edges")))
        assert (url, original, "reused_local_snapshot") in edges
        assert (original, BASE + "first", "observed_page_link") in edges
        assert frontier.db.execute("SELECT count(*) FROM observations WHERE parent=?", (original,)).fetchone()[0] == 1


def test_known_links_preserve_parents_without_consuming_fanout(tmp_path):
    with closing(Frontier(tmp_path / "ledger.sqlite")) as frontier:
        pages = init_pages(frontier, "seed", "known")
        with frontier.db:
            doc = frontier.import_document_bytes(
                b'<a href="known">web directory 1999</a><a href="new#one">a</a>'
                b'<a href="new#two">a again</a><a href="z">z</a>', "html", BASE + "seed", "archive")
        report = pages.reuse_local(max_children=1)
        assert report["page_states"] == {"queued": 2, "reused_local": 1}
        assert {r[0] for r in frontier.db.execute("SELECT url FROM page_tasks")} == {
            BASE + "known", BASE + "new", BASE + "seed"}
        edges = set(map(tuple, frontier.db.execute("SELECT child,relation FROM page_edges WHERE parent=?", (doc,))))
        assert (BASE + "known", "observed_page_link") in edges
        assert (BASE + "new", "observed_page_link") in edges
        assert (BASE + "z", "unreviewed_page_link") in edges


def test_fetched_parent_discovers_already_imported_child(tmp_path):
    with closing(Frontier(tmp_path / "ledger.sqlite")) as frontier:
        pages = init_pages(frontier, "seed")
        with frontier.db:
            frontier.import_document_bytes(b"issue", "html", BASE + "issue", "archive")
        replies = {
            "https://library.example.org/robots.txt": (404, {}, b""),
            BASE + "seed": (200, {"content-type": "text/html"}, b'<a href="issue">issue</a>'),
        }
        report = pages.run(3, 3, 1, 1, "test-agent", replies.pop, lambda delay: None)
        assert not replies
        assert report["page_states"] == {"parsed": 1, "reused_local": 1}
        assert report["request_kinds"] == {"page": 1, "robots": 1}
