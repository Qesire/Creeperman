"""Compare acquisition descriptors with the operator's local file inventory."""
import csv
import hashlib
import json
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

from .core import canonical


DDL = """
CREATE TABLE IF NOT EXISTS inventory_files(path TEXT PRIMARY KEY, size INTEGER NOT NULL, sha TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS inventory_sha ON inventory_files(sha);
CREATE INDEX IF NOT EXISTS inventory_size ON inventory_files(size);
CREATE TABLE IF NOT EXISTS inventory_urls(url TEXT, sha TEXT, size INTEGER, PRIMARY KEY(url,sha,size));
"""
LENGTHS = {"sha256": 64, "sha1": 40, "md5": 32}


def locator_key(url):
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        parts = urlsplit(url)
        defaults = {"http": 80, "https": 443, "ftp": 21}
        if parts.scheme not in defaults or not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        host = parts.hostname
        if ":" in host:
            host = "[" + host + "]"
        if parts.port is not None and parts.port != defaults[parts.scheme]:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def size_value(value):
    if type(value) is int or (isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value)):
        n = int(value)
        if 0 <= n <= 2**63 - 1:
            return n
    raise ValueError("invalid file size")


def checksum(value, algorithm):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{%d}" % LENGTHS[algorithm], value):
        raise ValueError(f"invalid {algorithm} digest")
    return value.lower()


def claims(record):
    result = {}
    for alg in LENGTHS:
        value = record.get("declared_" + alg)
        if value is not None:
            result[alg] = checksum(value, alg)
    value = record.get("declared_checksum")
    if value is not None:
        if not isinstance(value, str) or ":" not in value:
            raise ValueError("invalid declared checksum")
        alg, value = value.split(":", 1)
        alg = alg.lower().replace("-", "")
        if alg not in LENGTHS:
            raise ValueError("unsupported checksum")
        value = checksum(value, alg)
        if alg in result and result[alg] != value:
            raise ValueError("inconsistent checksum claims")
        result[alg] = value
    return result


def local_path(root, relative):
    if not relative or PureWindowsPath(relative).drive or Path(relative).is_absolute() or ".." in PureWindowsPath(relative).parts:
        raise ValueError("expected a relative inventory path")
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("inventory path leaves root")
    return path


def bind_inventory(db, inventory, root, receipts=()):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("inventory root must be a directory")
    db.executescript(DDL)
    with db:
        db.execute("DELETE FROM inventory_files")
        db.execute("DELETE FROM inventory_urls")
        with Path(inventory).open(encoding="utf-8-sig", newline="") as fp:
            rows = csv.DictReader(fp, delimiter="\t")
            for columns in (("path", "bytes", "sha256"), ("相对路径", "字节", "SHA256")):
                if set(columns).issubset(rows.fieldnames or []):
                    break
            else:
                raise ValueError("inventory requires path, bytes and SHA256 columns")
            for row in rows:
                name, size, sha = (row[key] for key in columns)
                local_path(root, name)
                db.execute("INSERT INTO inventory_files VALUES(?,?,?)", (name, size_value(size), checksum(sha, "sha256")))
        for receipt in receipts:
            rows = json.loads(Path(receipt).read_text(encoding="utf-8-sig"))
            if not isinstance(rows, list):
                raise ValueError("expected a download receipt array")
            for row in rows:
                if row.get("state") != "downloaded" or row.get("status") != 200:
                    continue
                sha, size = checksum(row["sha256"], "sha256"), size_value(row["bytes"])
                for url in (row.get("url"), row.get("final_url")):
                    key = locator_key(url)
                    if key:
                        db.execute("INSERT OR IGNORE INTO inventory_urls VALUES(?,?,?)", (key, sha, size))
        db.execute("INSERT OR REPLACE INTO settings VALUES('inventory_root',?)", (str(root),))
        files, contents = db.execute("SELECT count(*), count(DISTINCT sha) FROM inventory_files").fetchone()
        urls = db.execute("SELECT count(DISTINCT url) FROM inventory_urls").fetchone()[0]
    return {"inventory_files": files, "distinct_contents": contents, "receipt_urls": urls}


class LocalCheck:
    def __init__(self, db):
        self.db = db
        setting = db.execute("SELECT value FROM settings WHERE key='inventory_root'").fetchone()
        self.root = Path(setting[0]) if setting else None
        self.hashes = {}
        self.bytes_hashed = 0

    def verified_hashes(self, name, size, sha, algorithms):
        # All conclusions are scoped to the current preflight. Recheck the bytes
        # on the next export, even if a former export recorded a match.
        try:
            path = local_path(self.root, name)
            stat = path.stat()
            if stat.st_size != size or not path.is_file():
                return None
            key = (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            cached = self.hashes.setdefault(key, {})
            missing = ({"sha256"} | set(algorithms)) - cached.keys()
            if missing:
                hashes = {alg: hashlib.new(alg, usedforsecurity=False) for alg in missing}
                with path.open("rb") as fp:
                    for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                        self.bytes_hashed += len(chunk)
                        for digest in hashes.values():
                            digest.update(chunk)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != key[1:]:
                    return None
                cached.update({a: h.hexdigest() for a, h in hashes.items()})
            return cached if cached["sha256"] == sha else None
        except (OSError, ValueError, RuntimeError):
            return None

    def match(self, url, size, expected):
        if self.root is None:
            return "needs_review", "inventory_unbound", {}
        receipts = []
        if url:
            receipts = self.db.execute("SELECT sha,size FROM inventory_urls WHERE url=?", (url,)).fetchall()
        if "sha256" in expected:
            files = self.db.execute("SELECT path,size,sha FROM inventory_files WHERE sha=? ORDER BY path", (expected["sha256"],))
        elif expected and size is not None:
            files = self.db.execute("SELECT path,size,sha FROM inventory_files WHERE size=? ORDER BY path", (size,))
        elif receipts:
            applicable = {(r[0], r[1]) for r in receipts if size is None or size == r[1]}
            if len(applicable) != 1:
                return "needs_review", "receipt_ambiguous_or_size_conflict", {}
            sha, receipt_size = applicable.pop()
            files = self.db.execute("SELECT path,size,sha FROM inventory_files WHERE sha=? AND size=? ORDER BY path", (sha, receipt_size))
        else:
            return "needs_review", "no_local_identity", {}
        for name, inventory_size, sha in files:
            if size is not None and inventory_size != size:
                continue
            hashes = self.verified_hashes(name, inventory_size, sha, expected)
            if hashes and all(hashes[alg] == value for alg, value in expected.items()):
                match = {"local_path": name, "local_sha256": sha, "local_bytes": inventory_size}
                if expected:
                    return "reuse_local", "verified_declared_checksum", match
                return "review_local_snapshot", "verified_download_receipt", match
        return "needs_review", "no_verified_local_match", {}

    def other_scheme_hint(self, url, size):
        if not url:
            return {}
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.port is not None:
            return {}
        scheme = "https" if parts.scheme == "http" else "http"
        alternate = parts._replace(scheme=scheme).geturl()
        decision, _, match = self.match(alternate, size, {})
        if decision == "review_local_snapshot":
            return {"related_receipt_url": alternate, **match}
        return {}


@contextmanager
def new_output(out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(out)
    with TemporaryDirectory(prefix=".precheck-", dir=out.parent) as tmp:
        stage = Path(tmp) / "output"
        stage.mkdir()
        yield stage
        stage.rename(out)


def emit_precheck(db, records, out):
    check = LocalCheck(db)
    seen = set()
    counts = Counter()
    with (out / "precheck.jsonl").open("wb") as audit, (out / "acquisition_queue.jsonl").open("wb") as queue:
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("expected a file descriptor object")
            url = locator_key(record.get("url"))
            match = {}
            try:
                expected = claims(record)
                size = size_value(record["size"]) if record.get("size") is not None else None
            except ValueError:
                decision, reason = "needs_review", "invalid_or_conflicting_descriptor"
                key = None
            else:
                # Preserve version and access restrictions across observations.
                qualifiers = {k: record[k] for k in ("version", "metadata_mtime", "access_hint", "license_hint") if k in record}
                key = hashlib.sha256(canonical([url, size, expected, qualifiers])).hexdigest() if url else None
                if key and key in seen:
                    decision, reason = "duplicate_in_batch", "same_acquisition_key"
                else:
                    decision, reason, match = check.match(url, size, expected)
                    if decision == "review_local_snapshot" and any(record.get(k) is not None for k in ("version", "metadata_mtime")):
                        decision, reason = "needs_review", "version_requires_confirmation"
                    if reason == "no_local_identity" and not expected:
                        match = check.other_scheme_hint(url, size)
                        if match:
                            reason = "other_scheme_snapshot_for_review"
                    if key:
                        seen.add(key)
            result = {"file": record, "decision": decision, "reason": reason, "acquisition_key": key, **match}
            counts[decision] += 1
            audit.write(canonical(result))
            if decision == "needs_review":
                queue.write(canonical(result))
    return {"inventory_bound": check.root is not None, "input_records": sum(counts.values()),
            "decisions": dict(counts), "bytes_hashed": check.bytes_hashed}


def write_precheck(db, records, out):
    with new_output(out) as stage:
        report = emit_precheck(db, records, stage)
        (stage / "report.json").write_bytes(canonical(report))
    return report
