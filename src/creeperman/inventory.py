"""Offline census: disk-backed candidate union, one streaming baseline pass.

Produces an opportunity inventory, never qualified or submission rows.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from .core import (ALL, YEARS, audit_binding, annual_masks, bit, canonical,
                   host, score, sha, weights, write_json)
from .sources import records


def census(baseline: Path, audit: Path, model: Path, sources: Path, out: Path):
    if out.exists():
        raise FileExistsError("choose a new output directory")
    binding, authority_rows = audit_binding(audit, model)
    if baseline.name != binding["baseline_id"]:
        raise ValueError("baseline directory name does not match authority")
    w = weights(model)
    cfg = json.loads(sources.read_text(encoding="utf-8"))
    entries = cfg["sources"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("no source inventory")
    ids = set()
    for e in entries:
        if not e["source_id"] or e["source_id"] in ids or not e["origin_family"]:
            raise ValueError("unique source_id and origin_family required")
        if e.get("allowed_by_competition") is not True:
            raise ValueError("explicit source eligibility required")
        if "commoncrawl" in e["origin_family"].lower().replace(" ", "").replace("-", ""):
            raise ValueError("Common Crawl candidate corpus excluded")
        ids.add(e["source_id"])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after complete baseline read and successful checks.
    with tempfile.TemporaryDirectory(prefix=".census-", dir=out.parent) as tmp:
        p = Path(tmp)
        db = sqlite3.connect(p / "staging.sqlite")
        try:
            db.executescript("""
              PRAGMA temp_store=FILE;
              CREATE TABLE hits(
                h TEXT NOT NULL, source TEXT NOT NULL, hint INTEGER NOT NULL,
                mentions INTEGER NOT NULL, sample_url TEXT, sample_line INTEGER NOT NULL,
                PRIMARY KEY(h,source)
              ) WITHOUT ROWID;
              CREATE TABLE resolved(
                h TEXT PRIMARY KEY, baseline_mask INTEGER NOT NULL
              ) WITHOUT ROWID;
            """)
            source_stats = {}
            source_info = {}
            with (p / "rejected.jsonl").open("wb") as rejected:
                for e in entries:
                    sid = e["source_id"]
                    path = (sources.parent / e["path"]).resolve()
                    if sha(path) != e["sha256"]:
                        raise ValueError(f"source fingerprint mismatch: {sid}")
                    source_info[sid] = dict(e)
                    stats = Counter()
                    batch = []
                    for line, item, reason in records(path, e["format"]):
                        stats["raw_records"] += 1
                        if item is None:
                            stats["rejected_records"] += 1
                            rejected.write(canonical({"source_id": sid, "line": line, "reason": reason}))
                            continue
                        stats["valid_observations"] += 1
                        y = item["observed_year"]
                        b = bit(y) if y is not None else 0
                        if y is not None and not b:
                            stats["outside_core_observations"] += 1
                        if y is None:
                            stats["undated_observations"] += 1
                        batch.append((item["hostname"], sid, b, 1, item["original_url"], line))
                        if len(batch) >= 20_000:
                            insert(db, batch)
                            batch.clear()
                    insert(db, batch)
                    if sha(path) != e["sha256"]:
                        raise ValueError(f"source changed during scan: {sid}")
                    source_stats[sid] = dict(stats)
            # Resolve only candidate hosts; do not store 140M baseline rows.
            candidates = iter(db.execute("SELECT DISTINCT h FROM hits ORDER BY h"))
            current = next(candidates, None)
            pending = []
            for h, mask in annual_masks(baseline, authority_rows):
                while current and current[0] < h:
                    pending.append((current[0], 0))
                    current = next(candidates, None)
                if current and current[0] == h:
                    pending.append((h, mask))
                    current = next(candidates, None)
                if len(pending) >= 20_000:
                    db.executemany("INSERT INTO resolved VALUES (?,?)", pending)
                    pending.clear()
            while current:
                pending.append((current[0], 0))
                current = next(candidates, None)
                if len(pending) >= 20_000:
                    db.executemany("INSERT INTO resolved VALUES (?,?)", pending)
                    pending.clear()
            db.executemany("INSERT INTO resolved VALUES (?,?)", pending)
            db.commit()

            # Optional already-qualified local ledger is intentionally not inferred
            # from input candidates. Supply it as a separately frozen authority
            # in a future qualification/import step; current census is B-only.
            union = Counter()
            by_source = {s: Counter(stats) for s, stats in source_stats.items()}
            union_ub = Decimal(0)
            hinted_ub = Decimal(0)
            per_year = Counter()
            tlds = Counter()
            with (p / "opportunities.jsonl").open("wb") as f, (p / "active_candidates.txt").open("w", encoding="ascii", newline="\n") as active:
                cur = db.execute("""SELECT hits.h,hits.source,hits.hint,hits.mentions,
                    hits.sample_url,hits.sample_line,resolved.baseline_mask
                    FROM hits JOIN resolved USING(h) ORDER BY hits.h,hits.source""")
                from itertools import groupby
                for h, group in groupby(cur, key=lambda r:r[0]):
                    g = list(group)
                    mask = g[0][-1]
                    missing = ALL & ~mask
                    hint = 0
                    for _, sid, b, count, url, line, _ in g:
                        hint |= b
                        st = by_source[sid]
                        st["unique_hosts"] += 1
                        st["new_to_core_baseline_hosts"] += int(mask == 0)
                        st["hosts_with_missing_years"] += int(missing != 0)
                        st["hinted_missing_host_years"] += (b & missing).bit_count()
                        st["all_missing_host_years_ceiling"] += missing.bit_count()
                    union["unique_hosts"] += 1
                    union["new_to_core_baseline_hosts"] += int(mask == 0)
                    union["hosts_with_missing_years"] += int(missing != 0)
                    union["all_missing_host_years_ceiling"] += missing.bit_count()
                    union["hinted_missing_host_years"] += (hint & missing).bit_count()
                    if mask == 0:
                        active.write(h + "\n")
                    if not missing:
                        continue
                    union_ub += score(missing, h, w)
                    hinted_ub += score(missing & hint, h, w)
                    tlds[h.rsplit(".", 1)[-1]] += 1
                    for y in YEARS:
                        if missing & bit(y):
                            per_year[str(y)] += 1
                    f.write(canonical({"hostname": h, "baseline_mask": mask,
                        "missing_mask": missing, "hint_mask": hint,
                        "hinted_missing_mask": missing & hint,
                        "sources": [{"source_id": r[1], "hint_mask": r[2],
                            "mentions": r[3], "sample_url": r[4], "sample_line": r[5]} for r in g]}))
            report = {"schema": "census-v1", "authority": binding,
                "scope": "six core years, baseline-only; not evidence qualification",
                "sources": source_info, "union": dict(union),
                "per_source_nonadditive": {s: dict(v) for s,v in by_source.items()},
                "missing_by_year_ceiling": {str(y):per_year[str(y)] for y in YEARS},
                "candidate_hosts_by_tld": dict(sorted(tlds.items())),
                "all_missing_eed_ceiling_not_score": str(union_ub),
                "hinted_missing_eed_ceiling_not_score": str(hinted_ub),
                "qualified_new_eed": None,
                "output_sha256": {n: sha(p/n) for n in ("opportunities.jsonl","active_candidates.txt","rejected.jsonl")}}
            write_json(p / "report.json", report)
        finally:
            db.close()
        (p / "staging.sqlite").unlink()
        # Move directory contents as a single rename, preserving the temporary
        # directory's cleanup contract. Destination must be new.
        p.rename(out)
    return report


def insert(db, batch):
    db.executemany("""INSERT INTO hits VALUES (?,?,?,?,?,?)
        ON CONFLICT(h,source) DO UPDATE SET
        hint=hits.hint|excluded.hint, mentions=hits.mentions+1,
        sample_url=coalesce(hits.sample_url,excluded.sample_url),
        sample_line=CASE WHEN hits.sample_url IS NULL AND excluded.sample_url IS NOT NULL
                         THEN excluded.sample_line ELSE hits.sample_line END""", batch)
    db.commit()
