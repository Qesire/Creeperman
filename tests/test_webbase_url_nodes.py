"""Host identity, physical node witnesses and atomic publication on synthetic LAW data."""
import gzip
import hashlib
import json
import runpy
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pq = pytest.importorskip("pyarrow.parquet")
script = Path(__file__).resolve().parents[1] / "scripts/webbase_url_nodes.py"
extract = runpy.run_path(str(script))["extract"]


def fixture(tmp_path, lines):
    source = tmp_path / "fixture.urls.gz"
    source.write_bytes(gzip.compress(b"\n".join(lines) + b"\n"))
    return source, hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()


def test_nonadjacent_hosts_across_chunks_preserve_first_url_bytes(tmp_path):
    first = "http://WWW.example.org/café".encode()
    lines = [first, b"http://WWW.example.org/abc", b"https://example.org:443/",
             b"http://www.net/", b"http://127.0.0.1/", b"ftp://other.example.net/",
             b"http://x.example.org?port=123", b"https://www.example.org:443/again",
             b"http://example.org:invalid/", b"http://example.org.museum/"]
    source, checksum = fixture(tmp_path, lines)
    out = tmp_path / "out"
    result = extract(source, out, checksum, len(lines), chunk_hosts=2)
    assert json.loads((out / "report.json").read_bytes()) == result
    assert result["physical_node_lines"] == 10 and result["valid_url_lines"] == 6
    assert result["distinct_hosts"] == 4 and result["qualification"] == "candidate_only"
    rows = {r["hostname"]: r for r in pq.read_table(out / "hosts.parquet").to_pylist()}
    assert rows["www.example.org"] == {
        "hostname":"www.example.org", "year":2001, "nodes":3, "first_line":1,
        "first_node_id":0, "first_url_bytes":first,
    }
    assert {h:r["first_line"] for h,r in rows.items()} == {
        "www.example.org":1, "example.org":3, "x.example.org":7, "example.org.museum":10,
    }
    with pytest.raises(FileExistsError):
        extract(source, out, checksum, len(lines))


@pytest.mark.parametrize("damage", ["checksum", "count", "utf8", "gzip"])
def test_input_failure_does_not_publish_partial_table(tmp_path, damage):
    lines = [b"http://example.org/", b"http://example.org/\xff" if damage=="utf8" else b"not a URL"]
    source, checksum = fixture(tmp_path, lines)
    if damage == "gzip":
        source.write_bytes(source.read_bytes()[:-4])
        checksum = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    target = tmp_path / "out"
    with pytest.raises((ValueError, EOFError)):
        extract(source, target, "0"*32 if damage=="checksum" else checksum, 3 if damage=="count" else 2)
    assert not target.exists()
