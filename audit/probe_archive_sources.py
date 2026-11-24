#!/usr/bin/env python3
"""Read bounded public archive ranges; never download an entire large index.

Python 3.10+, standard library only. Prints JSON; pass --output PATH to save it.
Identity encoding makes the recorded byte ranges and SHA-256 unambiguous.
This is an access/schema probe, not a source-yield or website-evidence audit.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter
import gzip
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


PROBES = (
    ("arquivo_roteiro_start", "https://arquivo.pt/datasets/cdxj/Roteiro.cdxj", 0, 4096),
    ("arquivo_roteiro_middle", "https://arquivo.pt/datasets/cdxj/Roteiro.cdxj", 5_000_000, 8192),
    ("arquivo_ia_start", "https://arquivo.pt/datasets/cdxj/IA.cdxj", 0, 8192),
    ("ukwa_cdx_directory", "https://www.webarchive.org.uk/datasets/ukwa.ds.2/cdx/", 0, 8192),
)


def probe(name: str, url: str, start: int, size: int) -> dict:
    request_headers = {
        "Range": f"bytes={start}-{start + size - 1}",
        "Accept-Encoding": "identity",
        "User-Agent": "Creeperman-source-probe/0.1",
    }
    result = {
        "name": name,
        "requested_url": url,
        "request_headers": request_headers,
        "whole_source_scanned": False,
        "requested_source_byte_start": start,
        "requested_source_byte_end_inclusive": start + size - 1,
    }
    try:
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            # The read bound also applies if a server ignores Range and returns 200.
            body = response.read(size)
            encoding = response.headers.get("Content-Encoding", "identity")
            result.update({
                "response_url": response.url,
                "status": response.status,
                "headers": {key: response.headers.get(key) for key in (
                    "Content-Range", "Content-Length", "Content-Type",
                    "Content-Encoding", "Last-Modified", "ETag",
                )},
                "response_body_bytes_read": len(body),
                "response_body_sha256": hashlib.sha256(body).hexdigest(),
                "body_encoding": encoding,
                "identity_source_range_confirmed": response.status == 206 and encoding == "identity",
            })
        if encoding != "identity":
            result["schema_status"] = "encoded_response_not_parsed"
            return result
        text = body.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if start:
            lines = lines[1:]  # The first line may begin before the requested range.
        if not body.endswith(b"\n"):
            lines = lines[:-1]
        records = []
        malformed = 0
        for line in lines:
            try:
                _, timestamp, payload = line.split(" ", 2)
                record = json.loads(payload)
                records.append({
                    "timestamp": timestamp,
                    "original_url": record.get("url"),
                    "status": record.get("status"),
                    "mime": record.get("mime"),
                    "filename": record.get("filename"),
                })
            except (ValueError, TypeError):
                malformed += 1
        result["complete_lines_read"] = len(lines)
        result["parsed_cdxj_lines"] = len(records)
        result["non_cdxj_lines"] = malformed
        result["sample_records"] = records[:4]
        if not records:
            result["text_prefix"] = text[:240]
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def scan_roteiro() -> dict:
    """Optional bounded full scan of the small Roteiro index, with HTTP gzip.

    The counting syntax is explicit and does not replace the competition's
    normalization/evidence policy. No baseline or language weights are loaded.
    """
    url = "https://arquivo.pt/datasets/cdxj/Roteiro.cdxj"
    started = time.monotonic()
    result = {"source_url": url, "whole_source_scanned": False}
    wire = bytearray()
    try:
        request = urllib.request.Request(url, headers={
            "Accept-Encoding": "gzip", "User-Agent": "Creeperman-source-probe/0.1",
        })
        with urllib.request.urlopen(request, timeout=20) as response:
            encoding = response.headers.get("Content-Encoding", "identity")
            if response.status != 200 or encoding not in ("gzip", "identity"):
                raise ValueError("full scan requires HTTP 200 and gzip/identity encoding")
            result["status"] = response.status
            result["body_encoding"] = encoding
            while True:
                if time.monotonic() - started > 90:
                    raise TimeoutError("90-second full-scan acquisition budget")
                block = response.read1(65536)
                if not block:
                    break
                wire.extend(block)
                if len(wire) > 20_000_000:
                    raise ValueError("20 MB encoded-response cap exceeded")
        raw = gzip.decompress(wire) if encoding == "gzip" else bytes(wire)
        if len(raw) > 20_000_000:
            raise ValueError("20 MB decoded-response cap exceeded")
        result.update({
            "wire_body_bytes": len(wire),
            "identity_source_bytes": len(raw),
            "identity_source_sha256": hashlib.sha256(raw).hexdigest(),
            "whole_source_scanned": True,
        })
    except (OSError, urllib.error.URLError, ValueError) as error:
        result.update({"error": f"{type(error).__name__}: {error}", "wire_body_bytes_read": len(wire)})
        return result

    counts, years, statuses, mimes = Counter(), Counter(), Counter(), Counter()
    all_hy, status200_hy, html200_hy, html2xx_hy = set(), set(), set(), set()
    seen_lines, seen_capture = set(), set()
    label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    for line in raw.splitlines():
        counts["lines"] += 1
        counts["duplicate_raw_lines"] += int(line in seen_lines)
        seen_lines.add(line)
        try:
            _, timestamp, payload = line.decode("utf-8").split(" ", 2)
            record = json.loads(payload)
            if len(timestamp) != 14:
                raise ValueError("timestamp length")
            year = dt.datetime.strptime(timestamp, "%Y%m%d%H%M%S").year
            parsed = urllib.parse.urlsplit(record["url"])
            hostname = parsed.hostname.lower()
            status = str(record.get("status", ""))
            mime = str(record.get("mime", "")).split(";", 1)[0].strip().lower()
        except (ValueError, KeyError, TypeError, AttributeError):
            counts["parse_errors"] += 1
            continue
        years[year] += 1
        statuses[status] += 1
        mimes[mime] += 1
        capture = (record["url"], timestamp, status, mime, record.get("digest"))
        counts["duplicate_capture_identity"] += int(capture in seen_capture)
        seen_capture.add(capture)
        if parsed.scheme.lower() not in ("http", "https"):
            counts["non_http_records"] += 1
            continue
        try:
            ipaddress.ip_address(hostname)
            counts["ip_records"] += 1
            continue
        except ValueError:
            pass
        labels = hostname.split(".")
        if not (len(hostname) <= 253 and len(labels) > 1
                and all(label.fullmatch(part) for part in labels)
                and re.fullmatch("[a-zA-Z]+", labels[-1])):
            counts["syntax_rejected_records"] += 1
            continue
        counts["syntax_valid_http_records"] += 1
        counts["www_records"] += int(hostname.startswith("www."))
        if not 1996 <= year <= 2001:
            counts["outside_core_records"] += 1
            continue
        pair = (hostname, year)
        all_hy.add(pair)
        if status == "200":
            counts["status200_records"] += 1
            status200_hy.add(pair)
        is_html = mime in ("text/html", "application/xhtml+xml")
        if is_html and status.isdigit() and 200 <= int(status) < 300:
            counts["html2xx_records"] += 1
            html2xx_hy.add(pair)
        if is_html and status == "200":
            counts["html200_records"] += 1
            html200_hy.add(pair)
    result.update({
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "counts": dict(counts), "capture_year_counts": dict(years),
        "http_status_counts": dict(statuses), "mime_counts": dict(mimes),
        "unique_core_hostname_year_all_status": len(all_hy),
        "unique_core_hostname_year_status200": len(status200_hy),
        "unique_core_hostname_year_html200": len(html200_hy),
        "unique_core_hostname_year_html2xx": len(html2xx_hy),
        "tld_hostname_year_all_status": dict(Counter(h.rsplit(".", 1)[-1] for h, _ in all_hy)),
        "tld_hostname_year_html200": dict(Counter(h.rsplit(".", 1)[-1] for h, _ in html200_hy)),
        "eed_upper_bound_for_parsed_set_if_all_novel_and_weight1": len(all_hy),
        "identity_policy": "original/url hostname; lowercase; www retained; HTTP(S); no IP; ASCII labels 1..63 chars; hostname <=253 chars; alphabetic terminal label; trailing-dot and underscore forms excluded, not repaired",
        "interpretation": "index counts only; no baseline difference, fixed-weight EED, website-evidence acceptance, or official contribution computed",
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full-roteiro", action="store_true", help="also scan only the small Roteiro index; gzip, 20 MB response and 90-second acquisition caps")
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "bounded access and schema probe only",
        "whole_source_scanned": False,
        "observations": [probe(*entry) for entry in PROBES],
    }
    if args.full_roteiro:
        report["roteiro_full_scan"] = scan_roteiro()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
