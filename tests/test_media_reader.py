"""Selective media acquisition contracts; no network or competition originals."""
import hashlib
import io
import json
import sqlite3

import pytest

from creeperman.media_reader import RangeReader, ISOReader, MediaError, main

URL = "https://archive.example.org/original.iso"


def transport_for(data, calls, *, etag='"version-one"'):
    def fetch(url, headers, cap):
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        calls.append((url, headers, cap))
        raw = data[start:end + 1]
        return 206, {"content-range": f"bytes {start}-{end}/{len(data)}", "etag": etag}, raw
    return fetch


def reader(tmp_path, data, calls, **kwargs):
    return RangeReader(URL, len(data), tmp_path / "cache.sqlite", block_size=2048,
                       transport=transport_for(data, calls), interval=0, **kwargs)


def test_exact_seek_and_persistent_cache_resume(tmp_path):
    data = bytes(range(256)) * 40; calls = []
    with reader(tmp_path, data, calls) as fp:
        fp.seek(2000)
        assert fp.read(200) == data[2000:2200]
        fp.seek(-50, io.SEEK_END)
        assert fp.read(80) == data[-50:]
        assert fp.read() == b""
        assert len(calls) == 3 and calls[1][1]["If-Match"] == '"version-one"'
    with reader(tmp_path, data, calls) as fp:
        fp.seek(2000)
        assert fp.read(200) == data[2000:2200]
        assert fp.report()["cost"]["requests"] == 0
        assert fp.report()["cost"]["bytes"] == 0
        assert len(calls) == 3


def test_changed_etag_rejected_without_mixing_chunks(tmp_path):
    data = b"a" * 8192; calls = []
    with reader(tmp_path, data, calls) as fp:
        assert fp.read(1) == b"a"
    with RangeReader(URL, len(data), tmp_path / "cache.sqlite", block_size=2048,
                     transport=transport_for(data, calls, etag='"different"'), interval=0) as fp:
        fp.seek(2048)
        with pytest.raises(MediaError, match="ETag changed"): fp.read(1)
        assert fp.db.execute("SELECT count(*) FROM media_chunks").fetchone()[0] == 1
        assert fp.report()["requests"] == 2


@pytest.mark.parametrize("status,headers,body,error", [
    (200, {}, b"ignored range", "expected HTTP 206"),
    (206, {"content-range": "bytes 1-2048/4096", "etag": '"x"'}, b"x" * 2048, "range bounds"),
    (206, {"content-range": "bytes 0-2047/4096", "etag": '"x"'}, b"short", "range bounds"),
    (206, {"content-range": "bytes 0-2047/4096", "etag": 'W/"weak"'}, b"x" * 2048, "strong ETag"),
])
def test_response_contract_never_caches_wrong_bytes(tmp_path, status, headers, body, error):
    calls = []
    def fetch(*args):
        calls.append(args); return status, headers, body
    with RangeReader(URL, 4096, tmp_path / "c.sqlite", block_size=2048, transport=fetch) as fp:
        with pytest.raises(MediaError, match=error): fp.read(1)
        report = fp.report()
        assert len(calls) == 1 and not report["chunks"]
        assert report["bytes"] == len(body)


def test_redirect_cost_budget_and_scope(tmp_path):
    calls = []
    def fetch(url, headers, cap):
        calls.append(url)
        return 302, {"location": "https://outside.example.net/object.iso"}, b"redirect"
    with RangeReader(URL, 4096, tmp_path / "c.sqlite", transport=fetch) as fp:
        with pytest.raises(MediaError, match="outside approved"): fp.read(1)
        assert len(calls) == 1 and fp.report()["bytes"] == 8
    data = b"a" * 4096
    with RangeReader(URL, len(data), tmp_path / "d.sqlite", block_size=2048,
                     max_requests=1, transport=transport_for(data, []), interval=0) as fp:
        fp.read(1); fp.seek(2048)
        with pytest.raises(MediaError, match="budget exhausted"): fp.read(1)
        assert fp.report()["requests"] == 1


def test_cached_redirect_is_rechecked_against_narrowed_hosts_after_restart(tmp_path):
    mirror = "https://mirror.example.org/original.iso"
    data = b"a" * 4096
    calls = []
    def fetch(url, headers, cap):
        calls.append(url)
        if url == URL:
            return 302, {"location": mirror}, b"redirect"
        assert url == mirror
        return transport_for(data, [])(url, headers, cap)
    cache = tmp_path / "redirect.sqlite"
    with RangeReader(URL, len(data), cache, block_size=2048, transport=fetch, interval=0,
                     allowed_hosts=("archive.example.org", "mirror.example.org")) as fp:
        assert fp.read(1) == b"a"
        assert fp.meta("final_url") == mirror
        assert fp.report()["requests"] == 2
    def must_not_request(*args):
        raise AssertionError("previously allowed mirror must not receive a new request")
    with RangeReader(URL, len(data), cache, block_size=2048, transport=must_not_request,
                     allowed_hosts=("archive.example.org",), interval=0) as fp:
        assert fp.read(1) == b"a"  # Already verified bytes remain reusable offline.
        fp.seek(2048)
        with pytest.raises(MediaError, match="outside approved"):
            fp.read(1)
        assert fp.report()["cost"]["requests"] == 0
        assert fp.report()["requests"] == 2
    assert calls == [URL, mirror]


def test_same_etag_on_new_final_uri_cannot_mix_resources_after_restart(tmp_path):
    mirror = "https://mirror.example.org/original.iso"
    moved = "https://mirror.example.org/another.iso"
    data = b"a" * 4096
    calls = []
    def initial(url, headers, cap):
        calls.append(url)
        if url == URL:
            return 302, {"location": mirror}, b"initial redirect"
        return transport_for(data, [])(url, headers, cap)
    cache = tmp_path / "uri-pinned.sqlite"
    allowed = ("archive.example.org", "mirror.example.org")
    with RangeReader(URL, len(data), cache, block_size=2048, transport=initial,
                     allowed_hosts=allowed, interval=0) as fp:
        assert fp.read(1) == b"a"
        assert fp.meta("validator_url") == mirror
    later = []
    def changed(url, headers, cap):
        later.append(url)
        if url == mirror:
            return 302, {"location": moved}, b"moved"
        # This different resource reuses the same strong ETag and total size.
        # The URI boundary must stop the request before this branch is reached.
        return transport_for(b"b" * len(data), [])(url, headers, cap)
    with RangeReader(URL, len(data), cache, block_size=2048, transport=changed,
                     allowed_hosts=allowed, interval=0) as fp:
        fp.seek(2048)
        with pytest.raises(MediaError, match="validator URI changed"):
            fp.read(1)
        assert fp.report()["cost"]["requests"] == 1  # Only the already bound URI.
        assert fp.report()["cost"]["bytes"] == len(b"moved")
        assert len(fp.report()["chunks"]) == 1
        assert fp.meta("validator_url") == fp.meta("final_url") == mirror
        fp.seek(0)
        assert fp.read(1) == b"a"
    assert calls == [URL, mirror] and later == [mirror]


def test_legacy_cache_requires_one_provenance_uri_before_extension(tmp_path):
    data = b"a" * 6144
    calls = []
    with reader(tmp_path, data, calls) as fp:
        fp.read(1)
        with fp.db:
            fp.db.execute("DELETE FROM media_meta WHERE key='validator_url'")
    with reader(tmp_path, data, calls) as fp:
        fp.seek(2048)
        assert fp.read(1) == b"a"
        assert fp.meta("validator_url") == URL
        with fp.db:
            fp.db.execute("DELETE FROM media_meta WHERE key='validator_url'")
            fp.db.execute("UPDATE media_requests SET url=? WHERE start=0", ("https://archive.example.org/other.iso",))
    with reader(tmp_path, data, calls) as fp:
        assert fp.read(1) == b"a"  # Do not discard or re-fetch original cached bytes.
        fp.seek(4096)
        with pytest.raises(MediaError, match="ambiguous validator URI"):
            fp.read(1)
        assert fp.report()["cost"]["requests"] == 0


def test_rate_limit_persists_and_does_not_retry(tmp_path):
    calls = []
    def fetch(*args):
        calls.append(args); return 429, {"retry-after": "600"}, b"slow down"
    for attempt in range(2):
        with RangeReader(URL, 4096, tmp_path / "c.sqlite", transport=fetch) as fp:
            with pytest.raises(MediaError): fp.read(1)
    assert len(calls) == 1


def test_cache_corruption_and_identity_reuse_are_rejected(tmp_path):
    data = b"a" * 4096
    with reader(tmp_path, data, []) as fp: fp.read(1)
    with sqlite3.connect(tmp_path / "cache.sqlite") as db:
        db.execute("UPDATE media_chunks SET body=?", (b"corrupted",))
    with reader(tmp_path, data, []) as fp:
        with pytest.raises(MediaError, match="hash mismatch"): fp.read(1)
    with pytest.raises(MediaError, match="different original"):
        RangeReader(URL, 8192, tmp_path / "cache.sqlite", block_size=2048)


def iso_fixture():
    pycdlib = pytest.importorskip("pycdlib")
    iso = pycdlib.PyCdlib(); iso.new(interchange_level=3)
    iso.add_directory(iso_path="/SITE")
    contents = {"/SITE/INDEX.LIS;1": b"example.org//00000001.htm http://example.org/\n",
                "/SITE/00000001.HTM;1": b"<title>Fixture original</title>"}
    streams = []
    for path, raw in contents.items():
        stream = io.BytesIO(raw); streams.append(stream)
        iso.add_fp(stream, len(raw), iso_path=path)
    unrelated = io.BytesIO(b"u" * (2 * 1024 * 1024)); streams.append(unrelated)
    iso.add_fp(unrelated, len(unrelated.getvalue()), iso_path="/UNUSED.BIN;1")
    out = io.BytesIO(); iso.write_fp(out); iso.close()
    return out.getvalue(), contents


def test_selective_iso_matches_mature_full_parser_and_avoids_full_object(tmp_path):
    pycdlib = pytest.importorskip("pycdlib")
    data, expected = iso_fixture(); calls = []
    with reader(tmp_path, data, calls) as fp:
        selective = ISOReader(fp)
        assert [r["member_path"] for r in selective.list_dir("/SITE")] == sorted(expected)
        full = pycdlib.PyCdlib(); full.open_fp(io.BytesIO(data))
        for path, value in expected.items():
            oracle = io.BytesIO(); full.get_file_from_iso_fp(oracle, iso_path=path)
            assert selective.read_file(path) == oracle.getvalue() == value
        full.close()
        assert fp.report()["bytes"] < len(data) // 20
        with pytest.raises(MediaError, match="extraction bound"):
            selective.read_file("/UNUSED.BIN;1", max_bytes=1024)
        with pytest.raises(ValueError): selective.read_file("/SITE/../UNUSED.BIN;1")


def test_local_cli_members_are_bound_to_actual_bytes(tmp_path):
    data, expected = iso_fixture(); path = tmp_path / "original.iso"; path.write_bytes(data)
    out = tmp_path / "selected"
    assert main(["--local", str(path), "--source-id", "fixture", "--origin-family", "fixture",
                 "--directory", "/SITE", "--member", "/SITE/INDEX.LIS;1", "--out", str(out),
                 "--declared-sha1", "1" * 40]) == 0
    manifest = json.loads((out / "members.json").read_text())
    assert manifest["complete"] is True
    assert manifest["container"]["declared_sha1"] == "1" * 40
    assert "full_container_hash_verified" not in manifest["container"]
    member = manifest["members"][0]
    raw = (out / member["local_path"]).read_bytes()
    assert raw == expected["/SITE/INDEX.LIS;1"]
    assert hashlib.sha256(raw).hexdigest() == member["sha256"]
    assert "observed_year" not in member


def test_partial_http_failure_retains_received_bytes_and_never_caches(tmp_path, monkeypatch):
    from http.client import IncompleteRead
    from creeperman import media_reader
    class Response:
        code = 206
        headers = {"Content-Range": "bytes 0-2047/4096", "ETag": '"x"'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): raise IncompleteRead(b"partial", 2041)
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(media_reader, "build_opener", lambda *args: Opener())
    with RangeReader(URL, 4096, tmp_path / "partial.sqlite", block_size=2048) as fp:
        with pytest.raises(MediaError, match="IncompleteRead"): fp.read(1)
        report = fp.report()
        assert report["cost"]["bytes"] == 7
        assert report["attempts"][0]["status"] == 206
        assert "IncompleteRead" in report["attempts"][0]["error"]
        assert report["chunks"] == []
