"""Exact identities, frozen authority and bounded-memory membership."""
from __future__ import annotations

import hashlib
import heapq
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

YEARS = tuple(range(1996, 2002))
ALL = 63
VERSION = "exact-host-v1"
RULE = "candidate-only-v1"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(rf"(?:{LABEL}\.)+[a-z]{{2,63}}\Z", re.ASCII)


def host(value: str, *, candidate=True) -> str:
    h = value.strip().lower()
    if len(h) > 253 or not HOST.fullmatch(h):
        raise ValueError("invalid hostname")
    if candidate and re.fullmatch(r"www\.[a-z]+", h):
        raise ValueError("bare www.TLD; quarantine")
    return h


def url_host(url: str) -> str:
    p = urlsplit(url)
    if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("not a public HTTP URL identity")
    _ = p.port
    return host(p.hostname)


def bit(year: int) -> int:
    return 1 << (year - 1996) if year in YEARS else 0


def timestamp_year(timestamp: str) -> int:
    if not re.fullmatch(r"[0-9]{14}", timestamp):
        raise ValueError("expected full capture timestamp")
    return datetime.strptime(timestamp, "%Y%m%d%H%M%S").year


def canonical(data) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def weights(path: Path) -> dict[str, Decimal]:
    # Preserve the official percentage semantics (decimal, not binary float).
    m = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    result = {}
    for t, lang, pct in zip(m["tld"], m["lang"], m["perc_of_tld"], strict=True):
        if t and lang == "eng":
            t = str(t).lower()
            v = Decimal(str(pct)) / Decimal(100)
            if t in result or not v.is_finite() or not 0 <= v <= 1:
                raise ValueError("invalid or duplicate English weight")
            result[t] = v
    if not result:
        raise ValueError("empty model")
    return result


def audit_binding(audit_path: Path, model_path: Path) -> tuple[dict, dict]:
    a = json.loads(audit_path.read_text(encoding="utf-8"))
    if sha(model_path) != a["model_sha256"]:
        raise ValueError("model fingerprint mismatch")
    rows = {r["year"]: r for r in a["years"]}
    if len(a["years"]) != 6 or set(rows) != set(YEARS):
        raise ValueError("authority must contain exactly six years")
    for y, r in rows.items():
        if r["status"] != "OK" or r["normalized_order_inversions"] != 0:
            raise ValueError(f"unverified sorted authority: {y}")
    binding = {
        "baseline_id": a["baseline"],
        "annual_sha256": {str(y): rows[y]["sha256"] for y in YEARS},
        "model_sha256": a["model_sha256"],
        "baseline_eed": a["core_total"]["equivalent_english_domains"],
        "normalization": VERSION,
    }
    binding["id"] = hashlib.sha256(canonical(binding)).hexdigest()
    return binding, rows


def annual_stream(path: Path, expected: dict):
    # Consumed to EOF before publishing; validates bytes, order and row count.
    hsh = hashlib.sha256()
    previous = None
    n = 0
    with path.open("rb") as f:
        for raw in f:
            hsh.update(raw)
            s = raw.decode("ascii").strip().lower()
            if not s:
                continue
            s = host(s, candidate=False)
            if previous is not None and s < previous:
                raise ValueError(f"unsorted baseline {path}")
            if s != previous:
                yield s
                n += 1
            previous = s
    if hsh.hexdigest() != expected["sha256"] or n != expected["unique_valid_domains"]:
        raise ValueError(f"baseline fingerprint/count mismatch: {path}")


def annual_masks(directory: Path, rows: dict):
    # A six-way streaming merge; input authority files are already sorted.
    def tagged(y):
        for h in annual_stream(directory / f"{y}.txt", rows[y]):
            yield h, bit(y)
    previous, mask = None, 0
    for h, b in heapq.merge(*(tagged(y) for y in YEARS)):
        if h != previous:
            if previous is not None:
                yield previous, mask
            previous, mask = h, b
        else:
            mask |= b
    if previous is not None:
        yield previous, mask


def score(mask: int, h: str, w: dict) -> Decimal:
    return Decimal(mask.bit_count()) * w.get(h.rsplit(".", 1)[-1], Decimal(0))


def jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                yield n, json.loads(line)


def write_json(path: Path, data):
    path.write_bytes(canonical(data))
