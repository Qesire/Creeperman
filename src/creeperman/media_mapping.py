"""Recover explicit URL identities from original-media members, without network I/O.

Archive95's first-party importer consumes ``archives/<source>.json`` records
with raw ``url/path/archived/modified/warn/error/broken/skip`` fields. Its
Packard Bell (netonacd) restoration binds ``tppabs`` to the *preceding*
rewritten attribute and treats ``error`` as a failed download. Format source:
https://github.com/WumboSpasm/archive95-server/blob/9f6789d6c78db6d6cb2dee4d8c05ce67cc4f64ff/src/build.js

This adapter independently implements those bindings. It does not use the
restorer's www normalization or heuristic broken-URL repairs. All output is
unreviewed discovery material; dates and HTTP success are never inferred from
the presence of a file, its name, or the publication date of the container.

The PC Press LIS grammar was additionally checked against the actual ISO
members /WORLDWEB/WWW/{10,104}/INDEX.LIS;1 and 00000001.HTM;1 on 2026-11-28.
Each observed row is ``downloader-root//numbered-file original-URL``. The
numbered file is a sibling of INDEX.LIS in the ISO; downloader-root is not a
directory to manufacture or a hostname to add to the candidate pool.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import unquote, urljoin, urlsplit

from .core import canonical
from .extract import ATTRS, MAX_BODY, clean_url, clue, decode_body


VERSION = "media-mapping-v1"
SYNTAX_VERSION = "media-html-syntax-v1"
FORMAT_SOURCE = (
    "https://github.com/WumboSpasm/archive95-server/blob/"
    "9f6789d6c78db6d6cb2dee4d8c05ce67cc4f64ff/src/build.js"
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def member_key(value):
    """DOS/ISO spelling comparison only; preserve the actual member separately."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("nonempty member path required")
    parts = value.replace("\\", "/").strip("/").split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise ValueError("unsafe or ambiguous member path")
    return "/".join(re.sub(r";[0-9]+$", "", p).casefold() for p in parts)


class Members:
    """Read only hash-checked, bounded files explicitly listed in a manifest."""
    def __init__(self, manifest):
        self.path = Path(manifest).resolve()
        with self.path.open("rb") as f:
            raw = f.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError("member manifest exceeds bound")
        self.sha256 = digest(raw)
        self.manifest = json.loads(raw)
        if self.manifest.get("schema") != "media-members-v1":
            raise ValueError("expected media-members-v1")
        if not isinstance(self.manifest.get("container"), dict):
            raise ValueError("container identity is required")
        if not self.manifest.get("source_id") or not self.manifest.get("origin_family"):
            raise ValueError("source and acquisition family required")
        self.by_key = {}
        for row in self.manifest["members"]:
            key = member_key(row["member_path"])
            if key in self.by_key:
                raise ValueError("ambiguous case/version alias in member manifest")
            if (not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
                    or type(row.get("bytes")) is not int or row["bytes"] < 0):
                raise ValueError("member requires actual SHA-256 and byte length")
            p = Path(row["local_path"])
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("local member path must remain inside bundle")
            full = (self.path.parent / p).resolve()
            if not full.is_relative_to(self.path.parent):
                raise ValueError("local member escapes bundle")
            self.by_key[key] = {**row, "file": full}
        self.bytes_read = 0

    def get(self, path):
        return self.by_key.get(member_key(path))

    def read(self, row, max_bytes=MAX_BODY):
        if row["bytes"] > max_bytes:
            raise ValueError("member exceeds extraction bound")
        # Re-resolve at use time so a changed symlink cannot escape the bundle.
        p = row["file"].resolve()
        if not p.is_relative_to(self.path.parent):
            raise ValueError("local member escapes bundle")
        with p.open("rb") as f:
            raw = f.read(max_bytes + 1)
        self.bytes_read += len(raw)
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise ValueError("member hash/length mismatch")
        return raw


def archive95_mapping(raw, mapping_member, *, root=""):
    """Read the raw first-party JSON contract; do not consume normalizedUrl."""
    entries = json.loads(decode_body(raw))
    if not isinstance(entries, list):
        raise ValueError("Archive95 mapping is an array of explicit records")
    rows = []
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or "path" not in entry or "url" not in entry:
            raise ValueError("Archive95 entry requires path and raw url")
        path = (root.rstrip("/\\") + "/" if root else "") + entry["path"]
        member_key(path)
        rows.append({
            "member_path": path, "original_url": entry["url"],
            "mapping_locator": f"{mapping_member}:entry:{n}",
            "mapping_sha256": digest(raw), "mapping_basis": "archive95-explicit-raw-url",
            "date_claims": [
                {"value": entry[k], "semantics": "mapping_" + k + "_unreviewed"}
                for k in ("archived", "modified") if entry.get(k) is not None
            ],
            "flags": {k: entry.get(k) for k in ("warn", "error", "broken", "skip")},
        })
    return rows


def pcpress_mapping(raw, mapping_member):
    """Parse the inspected LIS grammar, quarantining all unsupported rows."""
    parent = mapping_member.replace("\\", "/").rsplit("/", 1)[0]
    rows, rejected = [], []
    checksum = digest(raw)
    for n, text in enumerate(decode_body(raw).splitlines(), 1):
        if not text.strip():
            continue
        locator = f"{mapping_member}:line:{n}"
        fields = text.split()
        if len(fields) != 2:
            rejected.append({"mapping_locator": locator, "mapping_sha256": checksum,
                             "reason": "unsupported_pcpress_lis_row", "raw_row": text})
            continue
        local, original = fields
        namespace, separator, filename = local.partition("//")
        if (not separator or not namespace or any(c in namespace for c in "/\\")
                or not re.fullmatch(r"[0-9]{8}\.[A-Za-z0-9]{1,8}", filename)):
            rejected.append({"mapping_locator": locator, "mapping_sha256": checksum,
                             "reason": "unsupported_pcpress_lis_path", "raw_row": text})
            continue
        rows.append({"member_path": parent + "/" + filename, "original_url": original,
                     "mapping_locator": locator, "mapping_sha256": checksum,
                     "mapping_basis": "pcpress-lis-explicit-sibling-filename",
                     "mapping_namespace": namespace, "raw_mapping_path": local,
                     "date_claims": [], "flags": {}})
    return rows, rejected


class MediaSyntax(HTMLParser):
    """Parse syntax once. Never resolve URLs or collapse duplicate attributes here."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.base, self.date_hints = [], None, []
        self.anchors, self.text = [], ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchors.clear()
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or "").lower() == "download":
            self.date_hints.append({"value": a.get("content"),
                                    "semantics": "raw_download_meta_unreviewed",
                                    "position": list(self.getpos())})
        for i, (attr, value) in enumerate(attrs):
            if not value or attr not in (("href",) if tag == "base" else ATTRS.get(tag, ())):
                continue
            original = attrs[i + 1][1] if i + 1 < len(attrs) and attrs[i + 1][0] == "tppabs" else None
            r = {"tag": tag, "attribute": attr, "raw_reference": value,
                 "teleport_original": original, "position": list(self.getpos()),
                 "anchor_text": "", "context_before": self.text[-200:]}
            if tag == "base":
                if self.base is None:
                    self.base = r
            else:
                if len(self.refs) >= 100000:
                    raise ValueError("HTML reference bound exceeded")
                self.refs.append(r)
                if tag == "a" and attr == "href":
                    self.anchors.append(r)

    def handle_endtag(self, tag):
        if tag == "a":
            self.anchors.clear()

    def handle_data(self, data):
        self.text = (self.text + data)[-400:]
        for r in self.anchors:
            r["anchor_text"] = (r["anchor_text"] + data)[:500]

    def result(self):
        return {"references": self.refs, "base": self.base, "date_hints": self.date_hints}


class SyntaxCache:
    """Cache only HTML syntax by bytes/encoding/parser version, not URL identity."""
    def __init__(self, path=None, max_memory_entries=64, max_memory_bytes=8 * 1024 * 1024):
        self.memory = OrderedDict()
        self.max_memory_entries = max_memory_entries
        self.max_memory_bytes = max_memory_bytes
        self.memory_bytes = 0
        self.parsed = self.hits = 0
        self.db = sqlite3.connect(path) if path is not None else None
        if self.db is not None:
            self.db.execute("CREATE TABLE IF NOT EXISTS media_syntax(key TEXT PRIMARY KEY,sha256 TEXT NOT NULL,body BLOB NOT NULL)")

    def parse(self, raw, charset=None):
        key = digest(canonical([SYNTAX_VERSION, digest(raw), charset]))
        if key in self.memory:
            self.hits += 1
            self.memory.move_to_end(key)
            return self.memory[key][0]
        cached = self.db.execute("SELECT sha256,body FROM media_syntax WHERE key=?", (key,)).fetchone() if self.db else None
        if cached:
            if digest(cached[1]) != cached[0]:
                raise ValueError("syntax cache checksum mismatch")
            result = json.loads(cached[1])
            self.hits += 1
        else:
            parser = MediaSyntax()
            parser.feed(decode_body(raw, charset)); parser.close()
            result = parser.result()
            self.parsed += 1
            if self.db:
                encoded = canonical(result)
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO media_syntax VALUES(?,?,?)", (key, digest(encoded), encoded))
        # JSON length is a conservative cache accounting unit (multiplied for
        # Python object overhead); a large page can bypass the memory cache.
        size = len(canonical(result)) * 4
        if size <= self.max_memory_bytes:
            self.memory[key] = (result, size)
            self.memory_bytes += size
        while len(self.memory) > self.max_memory_entries or self.memory_bytes > self.max_memory_bytes:
            _, (_, old_size) = self.memory.popitem(last=False)
            self.memory_bytes -= old_size
        return result

    def close(self):
        if self.db:
            self.db.close()


def local_target(member, raw):
    """Resolve an observed offline path inside the container, not on the Web."""
    p = urlsplit(raw)
    if p.scheme or p.netloc or not p.path:
        return None
    value = unquote(p.path).replace("\\", "/")
    parts = [] if value.startswith("/") else member.replace("\\", "/").strip("/").split("/")[:-1]
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return member_key("/".join(parts)) if parts else None


def resolve_reference(ref, *, original, member, mode, base, bindings):
    """Return (URL, basis). Unknown local paths stay unknown, never invented."""
    raw = ref["raw_reference"].strip()
    if mode == "teleport" and ref["teleport_original"] is not None:
        value = ref["teleport_original"].strip()
        if value == "error":
            return None, "teleport_download_error"
        try:
            return clean_url(value), "teleport-tppabs-preceding-attribute"
        except ValueError:
            return None, "invalid_teleport_original"
    if not raw or raw.startswith("#"):
        return None, "same_document_fragment"
    try:
        p = urlsplit(raw)
        if p.scheme or p.netloc:
            return clean_url(urljoin(base if mode == "original" else original, raw)), "literal_web_reference"
        if mode == "original":
            return clean_url(urljoin(base, raw)), "original_relative_reference"
        target = local_target(member, raw)
        mapped = bindings.get(target)
        if mapped:
            # Offline query strings may be downloader bookkeeping. The mapped
            # original URL is authoritative; only the link fragment is carried.
            value = mapped["original_url"]
            if p.fragment:
                value = value.split("#", 1)[0] + "#" + p.fragment
            return clean_url(value), "offline_member_explicit_mapping"
    except (ValueError, TypeError):
        return None, "invalid_reference"
    return None, "unmapped_local_reference"


def build_bindings(rows, bundle):
    bindings, review, grouped = {}, [], {}
    for row in rows:
        reason = None
        if any(row["flags"].get(k) for k in ("skip", "error", "broken")):
            reason = "mapping_marks_unusable"
        else:
            try:
                clean_url(row["original_url"])
            except (ValueError, TypeError):
                reason = "no_valid_explicit_original"
        if reason:
            review.append({**row, "reason": reason})
            continue
        grouped.setdefault(member_key(row["member_path"]), []).append(row)
    for key, items in grouped.items():
        # Multiple claimed origins for the same path are not resolved by title,
        # URL popularity, entry order, or downloaded content similarity.
        identities = {canonical([r["original_url"], r["date_claims"]]) for r in items}
        if len(identities) != 1:
            review.extend({**r, "reason": "conflicting_member_identity"} for r in items)
            continue
        row = dict(items[0])
        row["mapping_locators"] = list(dict.fromkeys(r["mapping_locator"] for r in items))
        bindings[key] = row
    return bindings, review


def extract_bound_page(row, member, raw, bundle, bindings, mode, cache):
    parsed = cache.parse(raw)
    original = row["original_url"]
    loc = member["member_path"]
    provenance = {
        "manifest_sha256": bundle.sha256, "source_id": bundle.manifest["source_id"],
        "origin_family": bundle.manifest["origin_family"],
        "container": bundle.manifest["container"],
        "member_path": loc, "member_sha256": member["sha256"], "member_bytes": member["bytes"],
        "mapping_sha256": row["mapping_sha256"], "mapping_locator": row["mapping_locator"],
        "mapping_basis": row["mapping_basis"],
        "mapping_flags": row["flags"],
        "date_claims": row["date_claims"] + parsed["date_hints"],
        "date_status": "unreviewed", "body_status": "original_member_unreviewed",
    }
    metadata = {"date_semantics": "media_date_claims_unreviewed_no_capture_year",
                "media_provenance": provenance, "extraction_version": VERSION,
                "source_original_url": original}
    observations = [clue(original, None, "source_page_hint", loc, **metadata)]
    review = []
    base = original
    if mode == "original" and parsed["base"]:
        try:
            base = clean_url(urljoin(original, parsed["base"]["raw_reference"]))
        except ValueError:
            pass
    for ref in parsed["references"]:
        url, basis = resolve_reference(ref, original=original, member=loc, mode=mode,
                                       base=base, bindings=bindings)
        if url is None:
            if basis != "same_document_fragment":
                review.append({"member_path": loc, "member_sha256": member["sha256"],
                               "reason": basis, **ref})
            continue
        data = {k: v for k, v in ref.items() if k != "teleport_original"}
        rewrite = {"basis": basis, "original_attribute": ref["teleport_original"]}
        if basis == "offline_member_explicit_mapping":
            target = bindings[local_target(loc, ref["raw_reference"].strip())]
            rewrite.update({"target_member_path": target["member_path"],
                            "mapping_sha256": target["mapping_sha256"],
                            "mapping_locator": target["mapping_locator"]})
        observations.append(clue(url, None, "html_reference", loc, **metadata, **data,
                                 reference_role="navigation" if ref["tag"] in ("a", "area") else "embedded_or_form",
                                 rewrite=rewrite))
    # Stable per-observation IDs retain source identity even for identical bytes.
    for ordinal, observation in enumerate(observations):
        observation["record_id"] = digest(canonical([VERSION, bundle.sha256, loc, original, ordinal, observation]))
    return observations, review


def run(manifest, mapping_member, out, *, mapping_format="archive95-json", root="", link_mode="local-map",
        cache_path=None, max_pages=2000, max_input_bytes=128 * 1024 * 1024, scope_id=None):
    started = time.monotonic()
    operator_sha = digest(Path(__file__).read_bytes())
    if scope_id is not None and (not isinstance(scope_id, str) or not 1 <= len(scope_id) <= 256
                                 or any(c.isspace() or ord(c) < 32 for c in scope_id)):
        raise ValueError("scope_id must be a nonempty frozen scope identifier")
    if mapping_format not in ("archive95-json", "pcpress-lis") or link_mode not in ("local-map", "teleport", "original"):
        raise ValueError("unsupported explicitly selected format or link mode")
    if mapping_format == "pcpress-lis" and (root or link_mode != "local-map"):
        raise ValueError("PC Press LIS binds literal sibling filenames using local-map mode")
    if type(max_pages) is not int or max_pages < 1 or type(max_input_bytes) is not int or max_input_bytes < 1:
        raise ValueError("positive processing bounds required")
    out = Path(out)
    if out.exists():
        raise FileExistsError(out)
    bundle = Members(manifest)
    mapping_members = [mapping_member] if isinstance(mapping_member, str) else list(mapping_member)
    if not mapping_members or len({member_key(p) for p in mapping_members}) != len(mapping_members):
        raise ValueError("nonempty distinct mapping members required")
    selected_mappings = []
    for path in mapping_members:
        mapping = bundle.get(path)
        if mapping is None:
            raise ValueError("mapping must be a real, hash-checked manifest member")
        selected_mappings.append(mapping)
    operation_scope = {
        "kind": "media-mapping-selected-members-v1", "scope_id": scope_id,
        "mapping_members": [row["member_path"] for row in selected_mappings],
        "mapping_format": mapping_format, "mapping_root": root, "link_mode": link_mode,
    }
    if scope_id is not None and bundle.manifest.get("operation_scope") != operation_scope:
        raise ValueError("operation_scope must be frozen in the input manifest and match the selected members and modes")
    rows, parse_review, mapping_inputs = [], [], []
    for mapping in selected_mappings:
        mapping_raw = bundle.read(mapping, min(MAX_BODY, max_input_bytes - bundle.bytes_read))
        if mapping_format == "pcpress-lis":
            parsed, rejected = pcpress_mapping(mapping_raw, mapping["member_path"])
            rows.extend(parsed); parse_review.extend(rejected)
        else:
            rows.extend(archive95_mapping(mapping_raw, mapping["member_path"], root=root))
        mapping_inputs.append({"member_path": mapping["member_path"], "sha256": mapping["sha256"]})
    bindings, review = build_bindings(rows, bundle)
    review = parse_review + review
    missing_members = sum(key not in bundle.by_key for key in bindings)
    out.mkdir(parents=True)
    cache = SyntaxCache(cache_path)
    page_count = observation_count = 0
    stopped = None
    failure = None
    consumed = []
    try:
        with (out / "observations.jsonl").open("wb") as target:
            for key, row in bindings.items():
                member = bundle.by_key.get(key)
                if member is None:
                    review.append({**row, "reason": "mapped_member_not_extracted"})
                    continue
                if not re.search(r"\.html?(?:;[0-9]+)?$", member["member_path"], re.I):
                    review.append({**row, "reason": "not_selected_html_member"})
                    continue
                if page_count >= max_pages or bundle.bytes_read + member["bytes"] > max_input_bytes:
                    stopped = "local_processing_bound"
                    break
                raw = bundle.read(member)
                observations, unresolved = extract_bound_page(row, member, raw, bundle, bindings, link_mode, cache)
                for observation in observations:
                    target.write(canonical(observation))
                review.extend(unresolved)
                page_count += 1; observation_count += len(observations)
                consumed.append({"member_path": member["member_path"], "sha256": member["sha256"],
                                 "original_url": row["original_url"]})
            if digest(Path(__file__).read_bytes()) != operator_sha:
                raise ValueError("operator source changed during execution")
    except Exception as exc:
        failure = exc
        stopped = "local_processing_failure"
    finally:
        cache.close()
    for name, data in (("mappings.jsonl", rows), ("review.jsonl", review)):
        with (out / name).open("wb") as f:
            for row in data:
                f.write(canonical(row))
    report = {
        "schema": "media-mapping-receipt-v1", "operator_version": VERSION,
        "format_source": FORMAT_SOURCE, "mapping_format": mapping_format, "link_mode": link_mode,
        "inputs": {"manifest_sha256": bundle.sha256, "mapping_members": mapping_inputs,
                   "container": bundle.manifest["container"], "consumed_members": consumed},
        "bounds": {"max_pages": max_pages, "max_input_bytes": max_input_bytes},
        "complete_selected_scope": stopped is None, "stopped_reason": stopped,
        "completion_semantics": "selected_mapping_files_and_available_bound_html_classified",
        "error": type(failure).__name__ + ": " + str(failure) if failure else None,
        "mapping_records": len(rows), "usable_bindings": len(bindings), "pages_processed": page_count,
        "mapped_members_not_extracted": missing_members,
        "unsupported_mapping_rows": len(parse_review),
        "observations": observation_count, "review_items": len(review),
        "syntax_bodies_parsed": cache.parsed, "syntax_cache_hits": cache.hits,
        "qualification": "not_run", "baseline_difference": "not_run", "eed": None,
        "cost": {"requests": 0, "bytes": bundle.bytes_read,
                 "wall_millis": int((time.monotonic() - started) * 1000)},
        "cost_bytes_scope": "local_original_member_reads",
        "outputs": {name: digest((out / name).read_bytes()) for name in
                    ("observations.jsonl", "mappings.jsonl", "review.jsonl")},
    }
    if scope_id is not None:
        # The caller must declare this scope before execution. Historical
        # receipts created without a scope cannot be retroactively completed.
        report["inputs"]["operation_scope"] = operation_scope
        report["operation"] = {"kind": "discovery", "scope_id": scope_id,
                               "input_sha256": bundle.sha256, "operator_sha256": operator_sha,
                               "complete": stopped is None}
    (out / "report.json").write_bytes(canonical(report))
    if failure:
        raise failure
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--mapping-member", action="append", required=True)
    p.add_argument("--mapping-format", choices=("archive95-json", "pcpress-lis"), default="archive95-json")
    p.add_argument("--mapping-root", default="")
    p.add_argument("--link-mode", choices=("local-map", "teleport", "original"), default="local-map")
    p.add_argument("--cache", type=Path)
    p.add_argument("--scope-id", help="scope declared before this discovery operation")
    p.add_argument("--max-pages", type=int, default=2000)
    p.add_argument("--max-input-bytes", type=int, default=128 * 1024 * 1024)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    print(canonical(run(args.manifest, args.mapping_member, args.out, mapping_format=args.mapping_format,
                        root=args.mapping_root, link_mode=args.link_mode, cache_path=args.cache,
                        max_pages=args.max_pages, max_input_bytes=args.max_input_bytes,
                        scope_id=args.scope_id)).decode(), end="")


if __name__ == "__main__":
    main()
