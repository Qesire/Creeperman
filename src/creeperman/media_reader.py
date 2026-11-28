"""Read known ISO originals selectively with pycdlib and verified range caching.

The cache is a partial container, never proof of a complete original-file hash.
Remote chunks require a strong, unchanged ETag and exact Content-Range. Local
ISO files use the same member API without HTTP or copying the whole container.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sqlite3
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from http.client import HTTPException, IncompleteRead
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

from .core import canonical
from .locking import collector_lock
from .source_frontier import NoRedirect


class MediaError(OSError):
    pass


class ResponseReadError(MediaError):
    """Preserve received body bytes when an HTTP response ends unsuccessfully."""
    def __init__(self, cause, status, headers, raw):
        super().__init__(type(cause).__name__ + ": " + str(cause))
        self.status, self.headers, self.raw = status, headers, raw


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def public_url(url, hosts):
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or p.fragment or any(c.isspace() for c in url)):
        raise ValueError("exact public HTTPS object URL required")
    if not any(p.hostname == h or (h.startswith("*.") and p.hostname.endswith(h[1:])) for h in hosts):
        raise MediaError("redirect outside approved object hosts")
    return url


def http_transport(url, headers, cap):
    """Return at most cap response bytes; redirect hops are handled by the caller."""
    opener = build_opener(NoRedirect)
    try:
        response = opener.open(Request(url, headers=headers), timeout=30)
    except HTTPError as exc:
        response = exc
    with response:
        hs = {k.lower(): v for k, v in response.headers.items() if k.lower() in
              ("content-range", "content-length", "etag", "last-modified", "location", "retry-after", "content-encoding")}
        # Do not download the original if the server ignored Range. Store only
        # a small error body prefix for diagnostics; never parse it as ISO data.
        limit = cap if response.code == 206 else min(cap, 4096)
        raw = bytearray()
        read = getattr(response, "read1", response.read)
        try:
            while len(raw) < limit:
                piece = read(min(64 * 1024, limit - len(raw)))
                if not piece: break
                raw.extend(piece)
        except IncompleteRead as exc:
            raw.extend(exc.partial)
            raise ResponseReadError(exc, int(response.code), hs, bytes(raw)) from exc
        except (OSError, HTTPException) as exc:
            raise ResponseReadError(exc, int(response.code), hs, bytes(raw)) from exc
        return int(response.code), hs, bytes(raw)


class RangeReader(io.RawIOBase):
    mode = "rb"

    def __init__(self, url, size, cache, *, max_requests=32, max_bytes=8 * 1024 * 1024,
                 block_size=256 * 1024, user_agent="Creeperman/0.2", interval=4,
                 allowed_hosts=None, transport=http_transport, sleeper=time.sleep):
        super().__init__()
        self.hosts = tuple(allowed_hosts or (urlsplit(url).hostname,))
        self.url = public_url(url, self.hosts)
        if type(size) is not int or size < 1 or type(block_size) is not int or not 2048 <= block_size <= 1024 * 1024:
            raise ValueError("positive object size and 2KiB..1MiB block size required")
        if type(max_requests) is not int or max_requests < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("explicit positive cumulative cache budgets required")
        if not user_agent or any(c in user_agent for c in "\r\n") or interval < 0:
            raise ValueError("invalid request settings")
        self.size, self.block_size, self.pos = size, block_size, 0
        self.max_requests, self.max_bytes = max_requests, max_bytes
        self.agent, self.interval, self.transport, self.sleeper = user_agent, interval, transport, sleeper
        cache = Path(cache); cache.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS media_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS media_chunks(start INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,body BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS media_requests(id INTEGER PRIMARY KEY,url TEXT,start INTEGER,end INTEGER,
            started REAL,status INTEGER,headers TEXT,bytes INTEGER,sha256 TEXT,error TEXT);
        """)
        identity = {"schema": "media-range-cache-v1", "url": url, "size": size, "block_size": block_size}
        old = self.db.execute("SELECT value FROM media_meta WHERE key='identity'").fetchone()
        if old and json.loads(old[0]) != identity:
            self.db.close(); raise MediaError("cache belongs to a different original or chunk layout")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO media_meta VALUES('identity',?)", (canonical(identity).decode(),))
        self.cache_hits = 0
        self.memory = OrderedDict()
        self.touched = set()
        self.opened_at = time.monotonic()
        self.initial_requests, self.initial_bytes = self.db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM media_requests").fetchone()

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM media_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        target = offset if whence == io.SEEK_SET else self.pos + offset if whence == io.SEEK_CUR else self.size + offset if whence == io.SEEK_END else -1
        if type(target) is not int or target < 0:
            raise ValueError("invalid seek")
        self.pos = target
        return target

    def _chunk(self, start):
        self.touched.add(start)
        if start in self.memory:
            self.cache_hits += 1
            self.memory.move_to_end(start)
            return self.memory[start]
        row = self.db.execute("SELECT sha256,body FROM media_chunks WHERE start=?", (start,)).fetchone()
        if row:
            if sha256(row[1]) != row[0]:
                raise MediaError("cached chunk hash mismatch")
            self.cache_hits += 1
            self._remember(start, row[1])
            return row[1]
        if self.meta("unresolved_request"):
            raise MediaError("previous request did not finish; inspect its receipt before resuming")
        end = min(self.size, start + self.block_size) - 1
        url = self.meta("final_url", self.url)
        etag = self.meta("etag")
        validator_url = self.meta("validator_url")
        if etag and not validator_url:
            # Older caches retained each successful request URI but did not
            # have a dedicated validator binding. Extend only when every
            # cached chunk is attributable to one and the same final URI.
            count, uri_count, prior_url = self.db.execute("""
                SELECT count(DISTINCT c.start),count(DISTINCT r.url),min(r.url)
                FROM media_chunks c JOIN media_requests r ON r.start=c.start
                  AND r.sha256=c.sha256 AND r.bytes=length(c.body)
                WHERE r.status=206 AND r.error IS NULL
            """).fetchone()
            chunk_count = self.db.execute("SELECT count(*) FROM media_chunks").fetchone()[0]
            if count != chunk_count or uri_count != 1 or prior_url != url:
                raise MediaError("legacy cache has ambiguous validator URI; cached bytes remain readable")
            validator_url = prior_url
        for _ in range(5):
            # A cached redirect is not permission to use that host in a later
            # run whose explicitly approved host set may have been narrowed.
            url = public_url(url, self.hosts)
            if etag and url != validator_url:
                raise MediaError("validator URI changed; cached chunks are not mixed across resources")
            requests, used = self.db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM media_requests").fetchone()
            remaining = self.max_bytes - used
            if requests >= self.max_requests or remaining < end - start + 1:
                raise MediaError("cumulative range request/byte budget exhausted")
            until = float(self.meta("cooldown_until", "0"))
            if until > time.time():
                raise MediaError("provider cooldown active")
            last = self.db.execute("SELECT max(started) FROM media_requests").fetchone()[0]
            if last is not None:
                delay = self.interval - (time.time() - last)
                if delay > 0: self.sleeper(delay)
            headers = {"User-Agent": self.agent, "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
            if etag: headers["If-Match"] = etag
            with self.db:
                rid = self.db.execute("INSERT INTO media_requests(url,start,end,started,bytes) VALUES(?,?,?,?,0)",
                                      (url, start, end, time.time())).lastrowid
                self.db.execute("INSERT OR REPLACE INTO media_meta VALUES('unresolved_request',?)", (str(rid),))
            status, hs, raw, error = None, {}, b"", None
            try:
                status, hs, raw = self.transport(url, headers, min(remaining, end - start + 2))
                hs = {k.lower(): v for k, v in hs.items()}
                if len(raw) > remaining: raise MediaError("transport violated byte cap")
            except ResponseReadError as exc:
                status, hs, raw, error = exc.status, exc.headers, exc.raw, str(exc)
            except (OSError, TimeoutError) as exc:
                error = type(exc).__name__ + ": " + str(exc)
            with self.db:
                self.db.execute("UPDATE media_requests SET status=?,headers=?,bytes=?,sha256=?,error=? WHERE id=?",
                                (status, canonical(hs).decode(), len(raw), sha256(raw), error, rid))
                self.db.execute("DELETE FROM media_meta WHERE key='unresolved_request'")
                if status in (401, 403, 429, 503):
                    until = time.time() + 300
                    value = hs.get("retry-after")
                    if value:
                        try: until = max(until, time.time() + int(value))
                        except ValueError:
                            try: until = max(until, parsedate_to_datetime(value).timestamp())
                            except (ValueError, TypeError, OverflowError): pass
                    if status in (401, 403): until = 253402300799
                    self.db.execute("INSERT OR REPLACE INTO media_meta VALUES('cooldown_until',?)", (str(until),))
            if error: raise MediaError(error)
            if status in (301, 302, 303, 307, 308) and hs.get("location"):
                url = public_url(urljoin(url, hs["location"]), self.hosts)
                continue
            if status != 206: raise MediaError(f"expected HTTP 206, received {status}; no full download fallback")
            if hs.get("content-encoding", "identity").lower() != "identity":
                raise MediaError("encoded HTTP range response")
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", hs.get("content-range", ""))
            if not match or tuple(map(int, match.groups())) != (start, end, self.size) or len(raw) != end - start + 1:
                raise MediaError("range bounds, total size or body length changed")
            new_etag = hs.get("etag", "")
            if not re.fullmatch(r'"[^"\r\n]+"', new_etag):
                raise MediaError("strong ETag required for combining and resuming ranges")
            if etag and new_etag != etag: raise MediaError("original object ETag changed; cache not mixed")
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO media_meta VALUES('etag',?)", (new_etag,))
                self.db.execute("INSERT OR REPLACE INTO media_meta VALUES('validator_url',?)", (url,))
                self.db.execute("INSERT OR REPLACE INTO media_meta VALUES('final_url',?)", (url,))
                self.db.execute("INSERT INTO media_chunks VALUES(?,?,?)", (start, sha256(raw), raw))
            self._remember(start, raw)
            return raw
        raise MediaError("too many observed redirects")

    def _remember(self, start, raw):
        self.memory[start] = raw
        self.memory.move_to_end(start)
        while len(self.memory) > 8: self.memory.popitem(last=False)

    def read(self, size=-1):
        if size is None or size < 0: size = self.size - self.pos
        size = min(size, max(0, self.size - self.pos))
        # Bound a single parser allocation separately from transport budgets.
        if size > self.max_bytes: raise MediaError("single read exceeds configured memory/byte bound")
        result = bytearray()
        while len(result) < size:
            start = self.pos // self.block_size * self.block_size
            raw = self._chunk(start)
            begin = self.pos - start
            piece = raw[begin:begin + size - len(result)]
            result.extend(piece); self.pos += len(piece)
        return bytes(result)

    def readinto(self, buffer):
        raw = self.read(len(buffer)); buffer[:len(raw)] = raw; return len(raw)

    def report(self):
        count, used = self.db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM media_requests").fetchone()
        return {"schema": "media-range-receipt-v1", "container_url": self.url, "size": self.size,
                "coverage": "partial-container", "full_container_hash_verified": False,
                "etag": self.meta("etag"), "validator_url": self.meta("validator_url"),
                "requests": count, "bytes": used, "cache_hits_this_open": self.cache_hits,
                "used_chunk_starts_this_open": sorted(self.touched),
                "cost": {"requests": count - self.initial_requests, "bytes": used - self.initial_bytes,
                         "wall_millis": round((time.monotonic() - self.opened_at) * 1000)},
                "chunks": [dict(r) for r in self.db.execute("SELECT start,length(body) AS bytes,sha256 FROM media_chunks ORDER BY start")],
                "attempts": [dict(r) for r in self.db.execute("SELECT * FROM media_requests ORDER BY id")]}

    def close(self):
        if not self.closed:
            self.db.close()
        super().close()


class ISOReader:
    """Walk only requested ISO9660 directories using pycdlib's record parsers.

    PyCdlib.open_fp eagerly loads the complete directory tree, which can read
    hundreds of distant chunks before the caller sees the root. The lower-level
    parsers preserve ISO validation while this traversal loads only ancestors
    of requested members. Joliet/Rock Ridge aliases, interleaving, extended
    attributes and multi-extent members are not silently interpreted here.
    """
    def __init__(self, source):
        from pycdlib import headervd
        self.source = source
        self.source.seek(0, io.SEEK_END)
        self.size = self.source.tell()
        self.volume = None
        for sector in range(16, 80):
            self.source.seek(sector * 2048)
            raw = self.source.read(2048)
            if len(raw) != 2048 or raw[1:6] != b"CD001":
                raise MediaError("unsupported or truncated ISO9660 descriptor")
            if raw[0] == 1:
                self.volume = headervd.PrimaryOrSupplementaryVD(headervd.VOLUME_DESCRIPTOR_TYPE_PRIMARY)
                self.volume.parse(raw, sector)
                break
            if raw[0] == 255: break
        if self.volume is None or self.volume.logical_block_size() != 2048:
            raise MediaError("supported primary ISO9660 volume not found")
        self.records = {"/": self.volume.root_dir_record}
        self.directories = {}

    def _bytes(self, record, limit):
        if (record.file_flags & 0x80 or record.file_unit_size or record.interleave_gap_size or record.xattr_len):
            raise MediaError("multi-extent, interleaved or extended-attribute member requires full ISO adapter")
        start = record.extent_location() * 2048
        length = record.data_length
        if length > limit or start < 0 or start + length > self.size:
            raise MediaError("ISO member is outside the object or extraction bound")
        self.source.seek(start)
        raw = self.source.read(length)
        if len(raw) != length: raise MediaError("incomplete ISO member")
        return raw

    def _record(self, path):
        if not isinstance(path, str) or not path.startswith("/") or any(v in (".", "..") for v in path.split("/")):
            raise ValueError("absolute original ISO path required")
        path = path.rstrip("/") or "/"
        if path not in self.records:
            parent = path.rsplit("/", 1)[0] or "/"
            self.list_dir(parent)
        if path not in self.records: raise FileNotFoundError(path)
        return self.records[path]

    def list_dir(self, path="/"):
        from pycdlib import dr
        path = path.rstrip("/") or "/"
        parent = self._record(path)
        if not parent.is_dir(): raise NotADirectoryError(path)
        if path in self.directories: return self.directories[path]
        raw = self._bytes(parent, 4 * 1024 * 1024)
        rows = []
        pos = 0
        while pos < len(raw):
            length = raw[pos]
            if not length:
                pos = (pos // 2048 + 1) * 2048
                continue
            if length < 34 or pos + length > len(raw) or pos % 2048 + length > 2048:
                raise MediaError("invalid ISO directory record boundary")
            record = dr.DirectoryRecord()
            record.parse(self.volume, raw[pos:pos + length], parent)
            pos += length
            ident = record.file_identifier()
            if ident in (b"\x00", b"\x01", b".", b".."): continue
            name = ident.decode("ascii")
            if "/" in name or "\\" in name: raise MediaError("invalid ISO member identifier")
            member_path = path.rstrip("/") + "/" + name
            if member_path in self.records: raise MediaError("duplicate ISO member identity")
            self.records[member_path] = record
            rows.append({"member_path": member_path, "is_dir": record.is_dir(), "bytes": record.data_length,
                         "iso_recording_date_raw": record.date.record().hex()})
        self.directories[path] = rows
        return rows

    def read_file(self, path, max_bytes=1024 * 1024):
        record = self._record(path)
        if record.is_dir() or record.data_length > max_bytes:
            raise MediaError("member is not a file within the extraction bound")
        return self._bytes(record, max_bytes)

    def close(self): pass  # The caller owns the underlying local/range stream.


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--local", type=Path); src.add_argument("--url")
    p.add_argument("--size", type=int); p.add_argument("--cache", type=Path)
    p.add_argument("--declared-sha1", help="provider declaration only; not a full-file verification")
    p.add_argument("--allow-network", action="store_true")
    p.add_argument("--allowed-host", action="append")
    p.add_argument("--max-requests", type=int, default=32)
    p.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    p.add_argument("--block-size", type=int, default=256 * 1024)
    p.add_argument("--user-agent", default="CreepermanResearch/0.2 (+https://github.com/Qesire/Creeperman)")
    p.add_argument("--directory", default="/")
    p.add_argument("--member", action="append", default=[])
    p.add_argument("--source-id", required=True); p.add_argument("--origin-family", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    if a.url and not (a.allow_network and a.cache and a.size):
        p.error("remote originals require --allow-network --cache --size")
    if a.declared_sha1 and not re.fullmatch(r"[0-9a-fA-F]{40}", a.declared_sha1):
        p.error("--declared-sha1 must be a 40-character hexadecimal declaration")
    if a.out.exists(): raise FileExistsError(a.out)
    a.out.mkdir(parents=True)
    source = None; reader = None; error = None
    manifest = {"schema": "media-members-v1", "source_id": a.source_id, "origin_family": a.origin_family,
                "container": {"url": a.url, "size": a.size if a.url else a.local.stat().st_size}, "members": []}
    if a.declared_sha1: manifest["container"]["declared_sha1"] = a.declared_sha1.lower()
    lock = a.cache if a.url else a.out / "local-read"
    with collector_lock(lock):
        try:
            source = RangeReader(a.url, a.size, a.cache, max_requests=a.max_requests,
                                 max_bytes=a.max_bytes, block_size=a.block_size,
                                 user_agent=a.user_agent, allowed_hosts=a.allowed_host) if a.url else a.local.open("rb")
            reader = ISOReader(source)
            (a.out / "directory.json").write_bytes(canonical(reader.list_dir(a.directory)))
            for member in a.member:
                raw = reader.read_file(member)
                digest = sha256(raw); local = "members/" + digest
                (a.out / "members").mkdir(exist_ok=True)
                (a.out / local).write_bytes(raw)
                manifest["members"].append({"member_path": member, "local_path": local, "sha256": digest, "bytes": len(raw)})
        except (Exception, KeyboardInterrupt) as exc:
            error = type(exc).__name__ + ": " + str(exc)
        finally:
            if isinstance(source, RangeReader):
                receipt = source.report()
                receipt.update({"complete": error is None, "error": error,
                                "requested_directory": a.directory, "requested_members": a.member,
                                "selected_members": manifest["members"],
                                "source_id": a.source_id, "origin_family": a.origin_family})
                receipt_raw = canonical(receipt)
                manifest["container"]["partial_identity"] = {"etag": receipt["etag"], "coverage": "partial-container",
                    "range_receipt_sha256": sha256(receipt_raw)}
                (a.out / "range-receipt.json").write_bytes(receipt_raw)
            if reader: reader.close()
            if source: source.close()
            manifest["complete"] = error is None
            manifest["error"] = error
            (a.out / "members.json").write_bytes(canonical(manifest))
    print(canonical({"complete": error is None, "members": len(manifest["members"]), "error": error}).decode(), end="")
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
