"""Offline catalog-file checks against a project inventory and acquisition receipts."""
import csv
import hashlib
import json
from contextlib import closing

import pytest

from creeperman.source_frontier import Frontier, main
from creeperman.source_precheck import bind_inventory, write_precheck


def digest(data, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def inventory(root, files, *, chinese=False):
    manifest = root / "inventory.tsv"
    columns = ["相对路径", "字节", "SHA256"] if chinese else ["path", "bytes", "sha256"]
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(columns)
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            writer.writerow([name, len(data), digest(data)])
    return manifest


def receipt(path, *, url, data, filename):
    row = {"filename": filename, "url": url, "final_url": url, "status": 200,
           "state": "downloaded", "bytes": len(data), "sha256": digest(data)}
    path.write_text(json.dumps([row]), encoding="utf-8")
    return path


def descriptor(identity, url, **fields):
    return {"provider": "zenodo", "kind": "file_descriptor", "identity": identity,
            "file_name": identity.rsplit("/", 1)[-1], "url": url, **fields}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_other_scheme_receipt_is_a_hint_only(tmp_path):
    url = "https://catalog.example.org/versions/archive.tar.gz?a=1"
    payload = b"local copy"
    manifest = inventory(tmp_path, {"copies/data": payload})
    proof = receipt(tmp_path / "receipt.json", url=url, filename="file", data=payload)
    http = url.replace("https:", "http:")
    records = [descriptor("a", http), descriptor("b", http + "2"), descriptor("c", http.replace("catalog.", "www.")),
               descriptor("d", http, declared_sha256="0" * 64), descriptor("e", url, version="v2")]
    with closing(Frontier(tmp_path / "db")) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, [proof])
        report = write_precheck(frontier.db, records, tmp_path / "out")
    queue = read_jsonl(tmp_path / "out" / "acquisition_queue.jsonl")
    assert len(queue) == len(records)
    assert queue[0]["related_receipt_url"] == url and queue[0]["local_sha256"] == digest(payload)
    assert all("related_receipt_url" not in row for row in queue[1:])
    assert queue[-1]["reason"] == "version_requires_confirmation"
    assert report["bytes_hashed"] == len(payload)


def precheck(db, records, out):
    write_precheck(db, records, out)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["input_records"] == len(records)
    audit = read_jsonl(out / "precheck.jsonl")
    assert [row["file"] for row in audit] == records
    assert all(row["reason"] for row in audit)
    queue = read_jsonl(out / "acquisition_queue.jsonl")
    assert queue == [row for row in audit if row["decision"] == "needs_review"]
    return [row["decision"] for row in audit], queue


@pytest.mark.parametrize("chinese", [False, True])
def test_matches_content_by_hash_and_size_across_names(tmp_path, chinese):
    files = {"materials/a.bin": b"abcdef", "materials/b.bin": b"ghijkl"}
    manifest = inventory(tmp_path, files, chinese=chinese)
    url = "https://data.example.org/mirror/"
    records = [
        descriptor("10/new-name.gz", url + "a", size=6, declared_checksum="md5:" + digest(b"ghijkl", "md5")),
        descriptor("11/another-name.zip", url + "b", size="6", declared_sha1=digest(b"abcdef", "sha1")),
        descriptor("12/b.bin", url + "c", size=6, declared_md5=digest(b"zzzzzz", "md5")),
        descriptor("13/a.bin", url + "d", size=9, declared_sha1=digest(b"abcdef", "sha1")),
    ]
    with closing(Frontier(tmp_path / "db.sqlite")) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, [])
        decisions, queue = precheck(frontier.db, records, tmp_path / "out")
    assert decisions == ["reuse_local", "reuse_local", "needs_review", "needs_review"]
    assert len(queue) == 2


def test_receipt_requires_verified_local_bytes_and_records_the_copy_path(tmp_path):
    data = b"retained snapshot"
    manifest = inventory(tmp_path, {"copied/dump.zip": data, "publisher/current.zip": b"older"})
    base = "https://catalog.example.org/"
    good = receipt(tmp_path / "publisher/good.json", url=base + "current", data=data, filename="current.zip")
    missing = receipt(tmp_path / "publisher/missing.json", url=base + "missing", data=b"absent", filename="dump.zip")
    wrong = receipt(tmp_path / "publisher/wrong.json", url=base + "wrong", data=b"other", filename="current.zip")
    failed = tmp_path / "publisher/failed.json"
    failed.write_text(json.dumps([{"filename": "current.zip", "url": base + "failed", "state": "failed",
                                   "status": 503, "sha256": digest(data), "bytes": len(data)}]), encoding="utf-8")
    records = [descriptor("10/" + key, base + key) for key in ("current", "missing", "wrong", "failed")]
    with closing(Frontier(tmp_path / "db.sqlite")) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, [good, missing, wrong, failed])
        decisions, queue = precheck(frontier.db, records, tmp_path / "out")
    assert decisions == ["review_local_snapshot", "needs_review", "needs_review", "needs_review"]
    snapshot = read_jsonl(tmp_path / "out/precheck.jsonl")[0]
    assert (tmp_path / snapshot["local_path"]).read_bytes() == data
    assert snapshot["local_sha256"] == digest(data) and snapshot["local_bytes"] == len(data)
    assert len(queue) == 3


def test_same_url_versions_and_batch_duplicates_survive_restart(tmp_path):
    files = {"old/data.gz": b"2024", "new/data.gz": b"2025"}
    manifest = inventory(tmp_path, files)
    url = "https://catalog.example.org/download/latest"
    receipts = [receipt(tmp_path / name / "receipt.json", url=url, filename="data.gz", data=data)
                for name, data in [("old", b"2024"), ("new", b"2025")]]
    known = descriptor("10/data.gz", url, size=4, declared_checksum="sha256:" + digest(b"2024"))
    other = descriptor("10/data.gz", url, size=4, declared_checksum="sha256:" + digest(b"2026"))
    ambiguous = descriptor("10/data.gz", url)
    records = [known, other, dict(other), ambiguous]
    db_path = tmp_path / "db.sqlite"
    with closing(Frontier(db_path)) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, receipts)
        first = precheck(frontier.db, records, tmp_path / "first")
    with closing(Frontier(db_path)) as reopened:
        again = precheck(reopened.db, records, tmp_path / "second")
        with pytest.raises(FileExistsError):
            write_precheck(reopened.db, records, tmp_path / "first")
    assert first == again
    assert first[0] == ["reuse_local", "needs_review", "duplicate_in_batch", "needs_review"]
    assert len(first[1]) == 2


def test_changed_local_bytes_do_not_match_old_inventory_digest(tmp_path):
    data = b"catalog v1"
    manifest = inventory(tmp_path, {"downloads/object.gz": data})
    item = descriptor("8/object.gz", "https://catalog.example.org/object.gz", size=len(data),
                      declared_checksum="sha256:" + digest(data))
    (tmp_path / "downloads/object.gz").write_bytes(b"catalog v2")
    with closing(Frontier(tmp_path / "db.sqlite")) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, [])
        decisions, queue = precheck(frontier.db, [item], tmp_path / "out")
    assert decisions == ["needs_review"]
    assert len(queue) == 1


def test_failed_rebind_cannot_read_outside_root_or_erase_old_binding(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    data = b"retained"
    manifest = inventory(root, {"ok.bin": data})
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"other")
    bad = root / "invalid.tsv"
    bad.write_text(f"path\tbytes\tsha256\n../outside.bin\t5\t{digest(b'other')}\n", encoding="utf-8")
    item = descriptor("10/a", "https://catalog.example.org/a", size=8, declared_sha256=digest(data))
    with closing(Frontier(tmp_path / "db.sqlite")) as frontier:
        bind_inventory(frontier.db, manifest, root, [])
        with pytest.raises(ValueError):
            bind_inventory(frontier.db, bad, root, [])
        decisions, _ = precheck(frontier.db, [item], tmp_path / "out")
    assert decisions == ["reuse_local"]


def test_frontier_export_checks_each_observed_version_and_preserves_parent(tmp_path):
    data = b"first version"
    manifest = inventory(tmp_path, {"data.bin": data})
    url = "https://catalog.example.org/record/file"
    record = descriptor("20/file", url, size=len(data), rank=4)
    records = [dict(record, declared_sha256=digest(version)) for version in [data, b"later version"]]
    with closing(Frontier(tmp_path / "db.sqlite")) as frontier:
        bind_inventory(frontier.db, manifest, tmp_path, [])
        with frontier.db:
            for parent, seen in zip(("first", "second"), records):
                frontier.observe(parent, "zenodo", seen, 1)
        frontier.export(tmp_path / "export")
    audit = read_jsonl(tmp_path / "export/precheck.jsonl")
    assert [(r["file"]["parent"], r["decision"]) for r in audit] == [
        ("first", "reuse_local"), ("second", "needs_review")]
    assert all(r["file"]["locator"] == "1" for r in audit)
    assert read_jsonl(tmp_path / "export/acquisition_queue.jsonl") == [audit[1]]
    report = json.loads((tmp_path / "export/report.json").read_text(encoding="utf-8"))
    assert report["file_precheck"]["input_records"] == 2 and report["verified_new_eed"] is None


def test_imported_file_manifests_deduplicate_across_restarts_and_reject_partial_import(tmp_path):
    db_path = tmp_path / "ledger.sqlite"
    base = "https://catalog.example.org/"
    item = descriptor("42/data.gz", base + "data.gz", size=2)
    first = dict(item, declared_sha256=digest(b"v1"))
    second = dict(item, declared_sha256=digest(b"v2"))
    parents = []
    for source, records in [("original", [first]), ("mirror", [first, second])]:
        payload = "".join(json.dumps(record) + "\n" for record in records).encode()
        with closing(Frontier(db_path)) as frontier, frontier.db:
            parents.append(frontier.import_document_bytes(payload, "file-descriptors", base + source, source))
    assert parents[0] != parents[1]

    broken = tmp_path / "broken.jsonl"
    new_file = descriptor("99/partial", base + "partial")
    broken.write_text(json.dumps(new_file) + "\n{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        main(["--db", str(db_path), "import-document", "--input", str(broken),
              "--format", "file-descriptors", "--source-url", base + "broken", "--family", "broken"])

    with closing(Frontier(db_path)) as frontier:
        assert frontier.db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
        assert frontier.db.execute("SELECT count(*) FROM bodies").fetchone()[0] == 2
        frontier.export(tmp_path / "out")
    audit = read_jsonl(tmp_path / "out/precheck.jsonl")
    assert len(audit) == 3
    repeated = [row for row in audit if row["file"]["declared_sha256"] == first["declared_sha256"]]
    assert {row["file"]["parent"] for row in repeated} == set(parents)
    assert sorted(row["decision"] for row in repeated) == ["duplicate_in_batch", "needs_review"]
    queue = read_jsonl(tmp_path / "out/acquisition_queue.jsonl")
    assert len(queue) == 2
    assert {row["file"]["declared_sha256"] for row in queue} == {
        first["declared_sha256"], second["declared_sha256"]}
