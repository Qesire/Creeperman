"""Batch the existing live-ranking features without changing their semantics.

All statistics are read afresh for a selection. This deliberately has no
cross-selection reward cache: a newly settled batch must affect the next pick.
"""
from __future__ import annotations

import json
import math


def batch_features(policy, candidates):
    """Return (task row, registered node, features) for each supplied candidate.

    Previously every candidate recomputed the same source-group aggregate and
    issued one SELECT for each URL/anchor token. Aggregate groups once, and look
    up only this selection's distinct tokens in bounded parameter batches.
    """
    from .discovery_policy import tokens

    if not candidates:
        return []
    db = policy.db
    groups = {
        (r[0], r[1], r[2]): (r[3], r[4], r[5])
        for r in db.execute("""SELECT family,year,operator,count(*),
                coalesce(sum(CAST(net_eed AS REAL)*credit),0),coalesce(sum(requests),0)
            FROM (
                SELECT n.family,n.year,n.operator,b.id,b.net_eed,b.requests,max(t.credit) credit
                FROM discovery_batches b
                JOIN discovery_training t ON t.batch_id=b.id
                JOIN discovery_nodes n ON n.id=t.node_id
                WHERE b.prior=0
                GROUP BY n.family,n.year,n.operator,b.id
            ) GROUP BY family,year,operator""")
    }
    node_tokens = [tokens(n["url"], n["context"]) for _, n in candidates]
    distinct = sorted({term for ts in node_tokens for term in ts})
    scores = {}
    for start in range(0, len(distinct), 500):
        chunk = distinct[start:start + 500]
        placeholders = ",".join("?" for _ in chunk)
        for term, positive, negative in db.execute(
                f"SELECT term,pos,neg FROM discovery_terms WHERE term IN ({placeholders})", chunk):
            scores[term] = math.log((1.0 + positive) / (1.0 + negative))
    valued = []
    for (row, node), ts in zip(candidates, node_tokens):
        observed = json.loads(node["features"])
        arm = groups.get((node["family"], node["year"], node["operator"]), (0, 0, 0))
        features = {
            "unprocessed": 1,
            "direct_evidence": int(bool(observed.get("direct_evidence", False))),
            "year": node["year"] if node["year"] is not None else 9999,
            "arm_yield": arm[1] / max(1, arm[2]),
            "arm_attempts": arm[0],
            "input_order": node["seq"],
            # Preserve the old token order and only include observed terms, so
            # ties and floating point summation match the reference path.
            "path_score": sum(scores[t] for t in ts if t in scores),
            "static_priority": row["priority"],
            "depth": row["depth"],
            "local_available": int(bool(observed.get("local_available", False)) or "local_id" in row.keys()),
        }
        valued.append((row, node, features))
    return valued
