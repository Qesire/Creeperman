"""Compare equivalent full-frontier choices on a synthetic local workload.

No HTTP requests, historical hosts, evidence decisions, or production EED.
The reference reuses the former per-candidate feature queries; the optimized
path uses the actual Frontier.choose entry point with batched feature reads.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from statistics import median
import time
from unittest.mock import patch

from creeperman.discovery_policy import DEFAULT
from creeperman.source_frontier import Frontier, spec


def benchmark(count=1000, repeats=3):
    policy = {**DEFAULT, "explore_every": 100}
    f = Frontier(":memory:", policy=policy)
    try:
        for i in range(count):
            f.enqueue(spec("ia", "search", f"synthetic mapping 1999 term{i}"),
                      f"synthetic-family-{i % 8}", i % 3, i % 17,
                      "synthetic-seed", "publisher edition mapping manifest")
        f.db.executemany("INSERT INTO discovery_terms VALUES(?,?,?)",
                         [("mapping", 3, 1), ("manifest", 2, 0), ("term7", 5, 0)])
        f.db.commit()
        reference = lambda p, cs: [(r, n, p._features(n, r)) for r, n in cs]
        observations = {"reference": [], "batched": []}
        for _ in range(repeats):
            for mode in observations:
                calls = []
                f.db.execute("SAVEPOINT benchmark")
                context = patch("creeperman.discovery_rank.batch_features", reference) if mode == "reference" else nullcontext()
                try:
                    with context:
                        f.db.set_trace_callback(calls.append)
                        start = time.perf_counter()
                        row = f.choose(["ia"], 3)
                        elapsed = time.perf_counter() - start
                        f.db.set_trace_callback(None)
                    features = json.loads(f.db.execute("SELECT features FROM discovery_choices ORDER BY seq DESC LIMIT 1").fetchone()[0])
                    observations[mode].append({"seconds": elapsed, "sql_statements": len(calls),
                                               "choice": row["id"], "features": features})
                finally:
                    f.db.set_trace_callback(None)
                    f.db.execute("ROLLBACK TO benchmark")
                    f.db.execute("RELEASE benchmark")
        reference_row = observations["reference"][0]
        same = all(r["choice"] == reference_row["choice"] and r["features"] == reference_row["features"]
                   for rows in observations.values() for r in rows)
        if not same:
            raise AssertionError("optimized ranking changed the selected task or features")
        report = {"schema": "discovery-ranking-benchmark-v1", "data_kind": "synthetic_fixture",
                  "candidates": count, "repeats": repeats, "same_choice_and_features": same,
                  "scope": "full Frontier.choose; exploitation; local in-memory SQLite",
                  "network_requests": 0, "production_eed": "0"}
        for mode, rows in observations.items():
            report[mode] = {"median_seconds": median(r["seconds"] for r in rows),
                            "sql_statements": rows[0]["sql_statements"]}
        report["measured_speedup"] = report["reference"]["median_seconds"] / report["batched"]["median_seconds"]
        return report
    finally:
        f.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.candidates <= 20000 or not 1 <= args.repeats <= 10:
        parser.error("bounded local benchmark required")
    print(json.dumps(benchmark(args.candidates, args.repeats), indent=2))
