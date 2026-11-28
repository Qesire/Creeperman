"""Online discovery ranking with audited, delayed outcome feedback.

The URL/anchor token model is a small, interpretable ACHE-inspired learner.
Round-robin exploration and singleton diagnostics are depletion heuristics, not
Good-UCB confidence guarantees: these are overlapping, unequal-cost batches.
Only imported, independently reviewed settle outputs train the reward model.
HTTP failure and a merely parsed catalogue are never zero-EED training labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, deque
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

from .core import YEARS, canonical, host, jsonl, sha, weights
from .locking import collector_lock

SCHEMA = "creeperman-live-policy-v1"
FIELDS = {"unprocessed", "direct_evidence", "year", "arm_yield", "arm_attempts",
          "input_order", "path_score", "static_priority", "depth", "local_available"}
DEFAULT = {"schema": SCHEMA, "order_by": [
    {"field": "local_available", "direction": "desc"},
    {"field": "path_score", "direction": "desc"},
    {"field": "arm_yield", "direction": "desc"},
    {"field": "static_priority", "direction": "desc"},
    {"field": "depth", "direction": "asc"},
    {"field": "input_order", "direction": "asc"}],
    "explore_every": 5, "path_decay": 0.5,
    "provenance": {"status": "unvalidated_bootstrap_prior"}}
DDL = """
CREATE TABLE IF NOT EXISTS discovery_policy_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_nodes(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,
 family TEXT NOT NULL,year INTEGER,operator TEXT NOT NULL,url TEXT NOT NULL,
 context TEXT NOT NULL,features TEXT NOT NULL,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_edges(parent TEXT,child TEXT,
 PRIMARY KEY(parent,child));
CREATE INDEX IF NOT EXISTS discovery_edges_child ON discovery_edges(child,parent);
CREATE TABLE IF NOT EXISTS discovery_choices(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,node_id TEXT NOT NULL,policy_sha TEXT NOT NULL,
 mode TEXT NOT NULL,features TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_batches(
 id TEXT PRIMARY KEY,node_id TEXT,prior INTEGER NOT NULL,receipt_sha TEXT NOT NULL,
 requests INTEGER NOT NULL,bytes INTEGER NOT NULL,wall_millis INTEGER NOT NULL,
 net_eed TEXT NOT NULL,qualified_count INTEGER NOT NULL,new_count INTEGER NOT NULL,
 scope_id TEXT,complete INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS discovery_seen(
 hostname TEXT,year INTEGER,first_batch TEXT NOT NULL,prior INTEGER NOT NULL,weight TEXT NOT NULL,
 PRIMARY KEY(hostname,year));
CREATE TABLE IF NOT EXISTS discovery_batch_keys(
 batch_id TEXT,hostname TEXT,year INTEGER,PRIMARY KEY(batch_id,hostname,year));
CREATE TABLE IF NOT EXISTS discovery_training(
 batch_id TEXT,node_id TEXT,label INTEGER NOT NULL,credit REAL NOT NULL,tokens TEXT NOT NULL,
 PRIMARY KEY(batch_id,node_id));
CREATE INDEX IF NOT EXISTS discovery_training_node ON discovery_training(node_id,batch_id);
CREATE TABLE IF NOT EXISTS discovery_terms(term TEXT PRIMARY KEY,pos REAL NOT NULL,neg REAL NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_batch_receipts(
 batch_id TEXT PRIMARY KEY,report TEXT NOT NULL,reviewed_sha256 TEXT NOT NULL,records_sha256 TEXT);
CREATE TABLE IF NOT EXISTS discovery_reviewed_records(
 batch_id TEXT,hostname TEXT,year INTEGER,evidence_id TEXT,record TEXT NOT NULL,
 PRIMARY KEY(batch_id,hostname,year,evidence_id));
"""


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_policy(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("invalid live discovery policy schema")
    rules = value.get("order_by")
    if not isinstance(rules, list) or not rules:
        raise ValueError("policy needs an explicit ranking")
    used = set()
    for r in rules:
        if not isinstance(r, dict) or set(r) != {"field", "direction"}:
            raise ValueError("invalid ranking rule")
        if r["field"] not in FIELDS or r["field"] in used or r["direction"] not in ("asc", "desc"):
            raise ValueError("unsupported, repeated or unobservable live ranking field")
        used.add(r["field"])
    every = value.get("explore_every", 5)
    decay = value.get("path_decay", 0.5)
    if type(every) is not int or not 2 <= every <= 100:
        raise ValueError("explore_every must be an integer in 2..100")
    if isinstance(decay, bool) or not isinstance(decay, (int, float)) or not 0 < decay <= 1:
        raise ValueError("invalid path decay")
    if not isinstance(value.get("provenance"),dict) or value["provenance"].get("status") not in ("unvalidated_bootstrap_prior", "validated_replay"):
        raise ValueError("explicit policy provenance required")
    return {**value, "explore_every": every, "path_decay": decay}


def tokens(url, context):
    terms = re.findall(r"[^\W_]{3,32}", unquote(url + " " + context).casefold())
    return sorted(set(terms) - {"https", "http", "www", "html", "com", "org", "the", "and"})[:128]


def year_hint(text):
    """A ranking hint from observed text, never an adjudicated capture date."""
    values = [int(v) for v in re.findall(r"(?<!\d)(199[6-9]|200[01])(?!\d)", text)]
    return min(values) if values else None


class LivePolicy:
    def __init__(self, db, policy=None):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.db.executescript(DDL)
        columns={r[1] for r in self.db.execute("PRAGMA table_info(discovery_batches)")}
        if "scope_id" not in columns:self.db.execute("ALTER TABLE discovery_batches ADD COLUMN scope_id TEXT")
        if "complete" not in columns:self.db.execute("ALTER TABLE discovery_batches ADD COLUMN complete INTEGER NOT NULL DEFAULT 0")
        if "records_sha256" not in {r[1] for r in self.db.execute("PRAGMA table_info(discovery_batch_receipts)")}:
            self.db.execute("ALTER TABLE discovery_batch_receipts ADD COLUMN records_sha256 TEXT")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS discovery_completed_scope ON discovery_batches(node_id,scope_id) WHERE prior=0 AND complete=1")
        if policy is not None:
            if isinstance(policy, (str, Path)):
                policy = json.loads(Path(policy).read_text(encoding="utf-8"))
            value = validate_policy(policy)
            self.db.execute("INSERT OR REPLACE INTO discovery_policy_meta VALUES('policy',?)",
                            (canonical(value).decode(),))
            self.db.commit()
        row = self.db.execute("SELECT value FROM discovery_policy_meta WHERE key='policy'").fetchone()
        self.config = validate_policy(json.loads(row[0])) if row else None
        self.enabled = self.config is not None
        self.policy_sha = fingerprint(self.config) if self.config else None

    def resolve(self, value):
        if not value:
            return None
        for key in (value, "catalog:" + value, "document:" + value, "page:" + value,
                    "artifact:" + value):
            if self.db.execute("SELECT 1 FROM discovery_nodes WHERE id=?", (key,)).fetchone():
                return key
        return None

    def register(self, node_id, *, kind, family, url="", context="", year=None,
                 operator="source-page-v1", parent=None, features=None, state="queued"):
        if not isinstance(node_id, str) or not node_id or kind not in ("page", "catalog", "artifact", "document"):
            raise ValueError("invalid discovery node")
        if not isinstance(family, str) or not family or not operator:
            raise ValueError("node family/operator required")
        if year is not None and (type(year) is not int or year not in YEARS):
            raise ValueError("invalid year hint")
        features = features or {}
        if not isinstance(features, dict):
            raise ValueError("node features must be an object")
        self.db.execute("""INSERT INTO discovery_nodes(id,kind,family,year,operator,url,context,features,state)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            context=CASE WHEN instr(discovery_nodes.context,excluded.context)>0 THEN discovery_nodes.context
                         ELSE substr(discovery_nodes.context||' '||excluded.context,1,8000) END,
            year=coalesce(discovery_nodes.year,excluded.year),
            features=json_patch(discovery_nodes.features,excluded.features)
            """, (node_id, kind, family, year, operator, url, str(context)[:4000],
                    canonical(features).decode(), state))
        parent = self.resolve(parent)
        if parent and parent != node_id:
            self.db.execute("INSERT OR IGNORE INTO discovery_edges VALUES(?,?)", (parent, node_id))
        return node_id

    def link(self, parent, child):
        parent, child = self.resolve(parent), self.resolve(child)
        if parent and child and parent != child:
            self.db.execute("INSERT OR IGNORE INTO discovery_edges VALUES(?,?)", (parent, child))

    def state(self, node_id, state):
        key = self.resolve(node_id)
        if key:
            self.db.execute("UPDATE discovery_nodes SET state=? WHERE id=?", (state, key))

    def _register_row(self, kind, row):
        r = dict(row)
        if kind == "catalog":
            task = json.loads(r["spec"])
            from .source_frontier import endpoint
            node = "catalog:" + r["id"]
            self.register(node, kind=kind, family=r["family"], url=endpoint(task),
                          context=task["key"], year=year_hint(task["key"]),
                          operator="source-catalog-v1", state=r["state"])
            for parent, relation in self.db.execute("SELECT parent,relation FROM edges WHERE child=?", (r["id"],)):
                self.link(parent, node)
        else:
            scope = json.loads(r["body"])
            node = "page:" + r["url"]
            self.register(node, kind=kind, family=scope["family"], url=r["url"],
                          year=year_hint(r["url"]), state=r["state"])
            for parent, in self.db.execute("SELECT parent FROM page_edges WHERE child=?", (r["url"],)):
                self.link(parent, node)
        return self.db.execute("SELECT * FROM discovery_nodes WHERE id=?", (node,)).fetchone()

    def _features(self, node, row):
        observed = json.loads(node["features"])
        arm = self.db.execute("""SELECT count(*),coalesce(sum(CAST(net_eed AS REAL)*credit),0),coalesce(sum(requests),0)
            FROM (SELECT b.id,b.net_eed,b.requests,max(t.credit) credit
              FROM discovery_batches b JOIN discovery_training t ON t.batch_id=b.id
              JOIN discovery_nodes n ON n.id=t.node_id
              WHERE b.prior=0 AND n.family=? AND n.year IS ? AND n.operator=? GROUP BY b.id)""",
            (node["family"], node["year"], node["operator"])).fetchone()
        terms = tokens(node["url"], node["context"])
        scores = []
        for term in terms:
            r = self.db.execute("SELECT pos,neg FROM discovery_terms WHERE term=?", (term,)).fetchone()
            if r:
                scores.append(math.log((1.0 + r[0]) / (1.0 + r[1])))
        return {"unprocessed": 1, "direct_evidence": int(bool(observed.get("direct_evidence", False))),
                "year": node["year"] if node["year"] is not None else 9999,
                "arm_yield": arm[1] / max(1, arm[2]), "arm_attempts": arm[0],
                # Equal shared URL tokens cancel when comparing neighbours.
                # Dividing by all tokens would perversely favour a short,
                # generic URL over a matching informative anchor at cold start.
                "input_order": node["seq"], "path_score": sum(scores),
                "static_priority": row["priority"], "depth": row["depth"],
                "local_available": int(bool(observed.get("local_available", False)) or "local_id" in row.keys())}

    def select(self, kind, rows):
        rows = list(rows)
        if not rows:
            return None
        if not self.enabled:
            return rows[0]
        candidates = [(r, self._register_row(kind, r)) for r in rows]
        candidates = [(r,n) for r,n in candidates if n["state"] not in ("reviewed_complete","closed_exact_operation","consumed")]
        if not candidates:return None
        from .discovery_rank import batch_features
        valued = batch_features(self, candidates)
        count = self.db.execute("SELECT count(*) FROM discovery_choices").fetchone()[0]
        explore = (count + 1) % self.config["explore_every"] == 0
        if explore:
            attempts = {(r[0],r[1],r[2]):r[3] for r in self.db.execute("""SELECT n.family,n.year,n.operator,count(*)
                FROM discovery_choices c JOIN discovery_nodes n ON n.id=c.node_id
                GROUP BY n.family,n.year,n.operator""")}
            key = lambda v: (attempts.get((v[1]["family"],v[1]["year"],v[1]["operator"]), 0),
                             v[2]["arm_attempts"], v[2]["input_order"])
        else:
            key = lambda v: tuple(v[2][r["field"]] * (1 if r["direction"] == "asc" else -1)
                                  for r in self.config["order_by"]) + (v[2]["input_order"],)
        row, node, features = min(valued, key=key)
        self.db.execute("INSERT INTO discovery_choices(node_id,policy_sha,mode,features) VALUES(?,?,?,?)",
                        (node["id"], self.policy_sha, "explore" if explore else "exploit", canonical(features).decode()))
        return row

    def _ancestors(self, node_id):
        queue, seen = deque([(node_id, 0)]), set()
        while queue:
            node, distance = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            yield node, distance
            for parent, in self.db.execute("SELECT parent FROM discovery_edges WHERE child=? ORDER BY parent", (node,)):
                queue.append((parent, distance + 1))

    def import_settlement(self, directory, model, *, node_id=None, prior=False, cost=None,
                          complete=False, scope_id=None):
        """Import operator-owned settle outputs; this is not an evidence classifier.

        First import the current cumulative reviewed settlement with prior=True.
        All later imports need an operator declaration that the named bounded
        scope has no unfinished adjudication. Settle alone cannot establish
        completion. Parsed pages and partial outcomes remain unlabeled.
        """
        directory, model = Path(directory), Path(model)
        report_path = directory / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("schema") != "reviewed-delta-v1" or not report.get("rule_version"):
            raise ValueError("a completed settle output is required")
        authority = report["authority"]
        identity = {"authority": authority, "rule_version": report["rule_version"], "model_sha256": sha(model)}
        if identity["model_sha256"] != authority["model_sha256"]:
            raise ValueError("model does not match the settled authority")
        binding = self.db.execute("SELECT value FROM discovery_policy_meta WHERE key='binding'").fetchone()
        if binding and json.loads(binding[0]) != identity:
            raise ValueError("feedback authority/model/rules changed")
        if not binding and not prior:
            raise ValueError("import current cumulative prior settlement before awarding new EED")
        if not prior:
            if complete is not True or not isinstance(scope_id,str) or not scope_id.strip():
                raise ValueError("declare a completed bounded review scope; settle alone is not a completion receipt")
            node_id = self.resolve(node_id)
            if not node_id:
                raise ValueError("feedback must bind an observed discovery node")
        elif node_id is not None:
            raise ValueError("prior import must not be attributed as a new discovery")
        cost = cost or {"requests": 0, "bytes": 0, "wall_millis": 0}
        if set(cost) != {"requests", "bytes", "wall_millis"} or any(type(v) is not int or v < 0 for v in cost.values()):
            raise ValueError("complete nonnegative batch cost required")
        if not prior and not any(cost.values()):
            raise ValueError("new feedback needs measured batch cost, not a zero placeholder")
        w = weights(model)
        keys, counts = set(), Counter()
        for year in YEARS:
            path = directory / f"{year}.txt"
            if sha(path) != report["files"][str(year)]:
                raise ValueError("settlement output hash mismatch")
            last = None
            for value in path.read_text(encoding="ascii").splitlines():
                h = host(value)
                if h != value or (last is not None and h <= last):
                    raise ValueError("settlement identities must be sorted, exact and unique")
                keys.add((h, year)); counts[year] += 1; last = h
            if counts[year] != report["new_by_year"][str(year)]:
                raise ValueError("settlement annual count mismatch")
        reviewed = {}
        all_reviewed = {}
        for _, record in jsonl(directory / "reviewed_decisions.jsonl"):
            if (record.get("validation_status") != "verified_web_year"
                    or record.get("authority") != authority["id"]
                    or record.get("rule_version") != report["rule_version"]
                    or not record.get("reviewer") or not record.get("reason") or not record.get("evidence_id")):
                raise ValueError("unreviewed or mismatched settlement decision")
            key = record["hostname"], record["year"]
            all_reviewed[(*key,record["evidence_id"])] = record
            if key in keys:
                reviewed[key] = record
        if set(reviewed) != keys:
            raise ValueError("every settled key needs its reviewed decision")
        total = sum((w.get(h.rsplit(".", 1)[-1], Decimal(0)) for h, _ in keys), Decimal(0))
        if total != Decimal(report["local_reviewed_new_eed"]):
            raise ValueError("settled EED mismatch")
        receipt_sha = sha(report_path)
        # Two genuinely complete zero-yield scopes can have byte-identical
        # settle outputs. The operator's bounded-scope binding distinguishes
        # those outcomes; identity credit still deduplicates globally below.
        batch_id = fingerprint({"report": receipt_sha, "reviewed": sha(directory / "reviewed_decisions.jsonl"),
                                "node_id":node_id,"scope_id":scope_id,"prior":prior})
        existing = self.db.execute("SELECT * FROM discovery_batches WHERE id=?", (batch_id,)).fetchone()
        if existing:
            if bool(existing["prior"]) != bool(prior) or existing["node_id"] != node_id:
                raise ValueError("the same settlement cannot be reassigned or reused as new work")
            if not prior and (existing["scope_id"]!=scope_id or any(existing[k]!=cost[k] for k in cost)):
                raise ValueError("a completed receipt's scope and measured cost are immutable")
            # Older databases retained only summary rewards. A freshly validated
            # original settle output can backfill its exact, immutable records.
            with self.db:
                self._retain_settlement(batch_id,report,directory,all_reviewed)
            return {"idempotent": True, **dict(existing)}
        if prior and self.db.execute("SELECT 1 FROM discovery_batches WHERE prior=0 LIMIT 1").fetchone():
            raise ValueError("bind the entire cumulative prior ledger before importing any new rewards")
        if not prior and self.db.execute("SELECT 1 FROM discovery_batches WHERE node_id=? AND scope_id=? AND complete=1",
                                        (node_id,scope_id)).fetchone():
            raise ValueError("this bounded review scope has already been consumed")
        with self.db:
            if not binding:
                self.db.execute("INSERT INTO discovery_policy_meta VALUES('binding',?)", (canonical(identity).decode(),))
            new, eed = [], Decimal(0)
            for h, year in sorted(keys):
                weight = w.get(h.rsplit(".", 1)[-1], Decimal(0))
                inserted = self.db.execute("INSERT OR IGNORE INTO discovery_seen VALUES(?,?,?,?,?)",
                                           (h, year, batch_id, int(prior), str(weight))).rowcount
                if inserted and not prior:
                    new.append((h, year)); eed += weight
                self.db.execute("INSERT INTO discovery_batch_keys VALUES(?,?,?)", (batch_id, h, year))
            self.db.execute("INSERT INTO discovery_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (batch_id, node_id, int(prior), receipt_sha, cost["requests"], cost["bytes"],
                             cost["wall_millis"], str(eed), len(keys), len(new),scope_id,int(prior or complete)))
            self._retain_settlement(batch_id,report,directory,all_reviewed)
            if not prior:
                positive = int(eed > 0)
                decay = self.config["path_decay"] if self.config else DEFAULT["path_decay"]
                term_credit={}
                for ancestor, distance in self._ancestors(node_id):
                    node = self.db.execute("SELECT url,context FROM discovery_nodes WHERE id=?", (ancestor,)).fetchone()
                    ts = tokens(node["url"], node["context"])
                    credit = decay ** distance
                    self.db.execute("INSERT INTO discovery_training VALUES(?,?,?,?,?)",
                                    (batch_id, ancestor, positive, credit, canonical(ts).decode()))
                    for term in ts:
                        term_credit[term]=max(credit,term_credit.get(term,0.0))
                # A shared token gets at most one update per completed
                # settled scope, not one update for each graph ancestor.
                for term,credit in term_credit.items():
                    self.db.execute("""INSERT INTO discovery_terms VALUES(?,?,?) ON CONFLICT(term)
                        DO UPDATE SET pos=pos+excluded.pos,neg=neg+excluded.neg""",
                        (term, credit if positive else 0.0, credit if not positive else 0.0))
                self.state(node_id,"reviewed_complete")
        return {"idempotent": False, "batch_id": batch_id, "prior": prior, "qualified_count": len(keys),
                "new_count": len(new), "net_eed": str(eed), "path_training": not prior}

    def _retain_settlement(self,batch_id,report,directory,records):
        record_hash=hashlib.sha256()
        for key in sorted(records):record_hash.update(canonical(records[key]))
        retained = ((directory/"report.json").read_bytes().decode("utf-8"),
                    sha(directory/"reviewed_decisions.jsonl"),record_hash.hexdigest())
        old=self.db.execute("SELECT report,reviewed_sha256,records_sha256 FROM discovery_batch_receipts WHERE batch_id=?",(batch_id,)).fetchone()
        if old and (tuple(old[:2])!=retained[:2] or old[2] is not None and old[2]!=retained[2]):
            raise ValueError("retained settlement receipt changed")
        self.db.execute("INSERT OR IGNORE INTO discovery_batch_receipts VALUES(?,?,?,?)",(batch_id,*retained))
        self.db.execute("UPDATE discovery_batch_receipts SET records_sha256=? WHERE batch_id=? AND records_sha256 IS NULL",(retained[2],batch_id))
        self.db.executemany("INSERT OR IGNORE INTO discovery_reviewed_records VALUES(?,?,?,?,?)",
            ((batch_id,h,y,e,canonical(r).decode()) for (h,y,e),r in records.items()))

    def summary(self):
        amounts = [Decimal(r[0]) for r in self.db.execute("SELECT net_eed FROM discovery_batches WHERE prior=0")]
        singletons = self.db.execute("""SELECT count(*) FROM (SELECT k.hostname,k.year FROM discovery_batch_keys k
            JOIN discovery_batches b ON b.id=k.batch_id
            JOIN discovery_seen s ON s.hostname=k.hostname AND s.year=k.year
            WHERE b.prior=0 AND s.prior=0
            GROUP BY k.hostname,k.year HAVING count(*)=1)""").fetchone()[0]
        return {"enabled": self.enabled, "policy_sha256": self.policy_sha,
                "provenance": self.config.get("provenance") if self.config else None,
                "decisions": self.db.execute("SELECT count(*) FROM discovery_choices").fetchone()[0],
                "reviewed_batches": len(amounts), "net_eed": str(sum(amounts,Decimal(0))),
                "prior_bound": bool(self.db.execute("SELECT 1 FROM discovery_policy_meta WHERE key='binding'").fetchone()),
                "trained_path_nodes": self.db.execute("SELECT count(*) FROM discovery_training").fetchone()[0],
                "singleton_keys_diagnostic": singletons,
                "diagnostic_scope": "post-prior reviewed key incidences; batches overlap and are not IID",
                "missing_mass_confidence_claimed": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True, type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("configure"); q.add_argument("--policy", required=True, type=Path)
    q = sub.add_parser("import-settlement")
    q.add_argument("--settlement", required=True, type=Path); q.add_argument("--model", required=True, type=Path)
    q.add_argument("--node-id"); q.add_argument("--prior", action="store_true")
    q.add_argument("--complete",action="store_true",help="Declare no unresolved items in this bounded review scope")
    q.add_argument("--scope-id",help="Immutable artifact/version/operator range identifier, not a whole-source claim")
    q.add_argument("--requests", type=int, default=0); q.add_argument("--bytes", type=int, default=0)
    q.add_argument("--wall-millis", type=int, default=0)
    sub.add_parser("status")
    a = p.parse_args(argv)
    from .source_frontier import Frontier
    with collector_lock(a.db):
        f = Frontier(a.db, policy=a.policy if a.cmd == "configure" else None)
        try:
            if a.cmd == "import-settlement":
                result = f.policy.import_settlement(a.settlement, a.model, node_id=a.node_id, prior=a.prior,
                    cost={"requests": a.requests, "bytes": a.bytes, "wall_millis": a.wall_millis},
                    complete=a.complete,scope_id=a.scope_id)
            else:
                result = f.policy.summary()
            print(canonical(result).decode(), end="")
        finally:
            f.close()


if __name__ == "__main__":
    main()
