"""Explicit local source adapters; no network, no invented host variants."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from .core import host, url_host, timestamp_year
from .extract import FORMATS as EXTRA_FORMATS, extract
FORMATS = ('hosts','urls','observations','cdxj') + EXTRA_FORMATS


def records(path: Path, fmt: str):
    """Yield (line, parsed candidate or None, rejection reason).

    A date is a hint, not a website qualification. Original input plus line
    location is retained. CDXJ uses original URL, never the SURT key.
    """
    if fmt in EXTRA_FORMATS:
        for n,(item,error) in enumerate(extract(path,fmt),1):
            yield n,item,error
        return
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt}")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="strict") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                url, year, kind = None, None, "hostname_text"
                if fmt == "hosts":
                    h = host(line)
                elif fmt == "urls":
                    url = line
                    h, kind = url_host(url), "url_text"
                elif fmt == "cdxj":
                    _, ts, payload = line.split(maxsplit=2)
                    row = json.loads(payload)
                    url = row["url"]
                    h, year, kind = url_host(url), timestamp_year(ts), "capture_index_hint"
                else:
                    row = json.loads(line)
                    url = row.get("original_url")
                    h = url_host(url) if url else host(row["hostname"])
                    if row.get("hostname") and host(row["hostname"]) != h:
                        raise ValueError("original/hostname conflict")
                    year = row.get("observed_year")
                    if year is not None and (type(year) is not int or not 1 <= year <= 9999):
                        raise ValueError("invalid observation year")
                    kind = str(row.get("kind", "observation"))
                details = {k: row[k] for k in ("locator","source_original_url","anchor_text",
                    "context","context_before","reference_role","date_semantics","raw_reference",
                    "message_id","date_header","position","tag","attribute","rewrite",
                    "capture_date","record_id","capture_status","capture_timestamp","title","collection",
                    "catalog_manifest","catalog_ordinal","entity_name","project_title","acronym")
                    if k in row} if fmt=="observations" else {}
                yield n, {**details,"hostname": h, "original_url": url, "observed_year": year,
                          "kind": kind}, None
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                yield n, None, str(exc)
