"""Export predeclared discovery executions to RSIforme's recorded-action epoch.

Plans precede execution. A directory response alone is not a completed evidence
scope. Evidence outcomes require a retained reviewed settlement. A separately
declared discovery operation can complete with verified output artifacts and
no direct reward; its descendants retain their own evidence review scopes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .core import YEARS, annual_stream, audit_binding, canonical, sha, weights
from .locking import collector_lock
from .source_precheck import new_output

COSTS = ("requests", "bytes", "wall_millis")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
DDL = """
CREATE TABLE IF NOT EXISTS discovery_epochs(id TEXT PRIMARY KEY,context TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_epoch_prior(
 epoch_id TEXT,hostname TEXT,year INTEGER,PRIMARY KEY(epoch_id,hostname,year));
CREATE TABLE IF NOT EXISTS discovery_epoch_actions(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,epoch_id TEXT,action_id TEXT,node_id TEXT,
 plan TEXT NOT NULL,assets TEXT NOT NULL,parent_action TEXT,initial INTEGER NOT NULL,
 declared_ns INTEGER NOT NULL,batch_floor INTEGER NOT NULL,choice_seq INTEGER,
 operation_kind TEXT NOT NULL DEFAULT 'evidence_review',
 outcome TEXT,execution_sha TEXT,UNIQUE(epoch_id,action_id),UNIQUE(epoch_id,execution_sha));
CREATE TABLE IF NOT EXISTS discovery_execution_receipts(sha TEXT PRIMARY KEY,bytes BLOB NOT NULL);
"""


def digest(value):
    # RSIforme's canonical identity deliberately has no terminal newline.
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
                                    separators=(",", ":"),allow_nan=False).encode()).hexdigest()


def checked_cost(value):
    if (not isinstance(value,dict) or set(value)!=set(COSTS)
            or any(type(value[k]) is not int or value[k]<0 for k in COSTS)):
        raise ValueError("requests, bytes and wall_millis must be measured nonnegative integers")
    return value


def asset(path):
    path=Path(path).resolve(strict=True)
    return {"path":str(path),"sha256":sha(path)}


def verify_assets(items):
    for value in items.values():
        if sha(Path(value["path"]))!=value["sha256"]:
            raise ValueError("recorded input/operator/authority asset changed")


class DiscoveryEpoch:
    def __init__(self,frontier,epoch_id):
        if not isinstance(epoch_id,str) or not ID.fullmatch(epoch_id):
            raise ValueError("invalid epoch identifier")
        self.f,self.db,self.id=frontier,frontier.db,epoch_id
        self.db.executescript(DDL)
        if "operation_kind" not in {r[1] for r in self.db.execute("PRAGMA table_info(discovery_epoch_actions)")}:
            self.db.execute("ALTER TABLE discovery_epoch_actions ADD COLUMN operation_kind TEXT NOT NULL DEFAULT 'evidence_review'")

    def context(self):
        row=self.db.execute("SELECT context FROM discovery_epochs WHERE id=?",(self.id,)).fetchone()
        if row is None:raise ValueError("initialize the epoch before declaring actions")
        return json.loads(row[0])

    def initialize(self,*,baseline,audit,model,rules,budget,data_kind="recorded"):
        checked_cost(budget)
        if not any(budget.values()) or data_kind not in ("recorded","synthetic_fixture"):
            raise ValueError("positive budget and explicit data kind required")
        baseline=Path(baseline).resolve(strict=True)
        audit,model,rules=(Path(p).resolve(strict=True) for p in (audit,model,rules))
        authority,_=audit_binding(audit,model)
        bound=self.db.execute("SELECT value FROM discovery_policy_meta WHERE key='binding'").fetchone()
        if not bound or json.loads(bound[0])["authority"]!=authority or baseline.name!=authority["baseline_id"]:
            raise ValueError("bind the complete current reviewed prior and matching baseline authority first")
        with self.db:
            if self.db.execute("SELECT 1 FROM discovery_epochs WHERE id=?",(self.id,)).fetchone():
                raise ValueError("epoch is immutable; use a new identifier")
            self.db.execute("INSERT INTO discovery_epoch_prior SELECT ?,hostname,year FROM discovery_seen",(self.id,))
            # Hash a streamed, full A snapshot, not a supplied count or sample.
            reviewed_hash=hashlib.sha256()
            for h,y in self.db.execute("SELECT hostname,year FROM discovery_epoch_prior WHERE epoch_id=? ORDER BY hostname,year",(self.id,)):
                reviewed_hash.update(canonical({"hostname":h,"year":y}))
            context={"baseline":str(baseline),"authority":authority,"budget":budget,"data_kind":data_kind,
                     "assets":{k:asset(p) for k,p in (("audit",audit),("model",model),("rules",rules))},
                     "reviewed_sha256":reviewed_hash.hexdigest(),
                     "rule_version":json.loads(bound[0])["rule_version"],
                     "choice_floor":self.db.execute("SELECT coalesce(max(seq),0) FROM discovery_choices").fetchone()[0]}
            self.db.execute("INSERT INTO discovery_epochs VALUES(?,?)",(self.id,canonical(context).decode()))
        return {"epoch_id":self.id,"data_kind":data_kind,"production_ledger_written":False}

    def declare(self,action_id,*,node_id,input_path,operator_path,record_locator,capture_or_edition,
                cost_bound,initial=False,revealed_by=None,requires=(),features=None,choice_seq=None,
                operation_kind="evidence_review"):
        context=self.context();checked_cost(cost_bound)
        if not ID.fullmatch(action_id) or not record_locator or not capture_or_edition:
            raise ValueError("action identifier and exact operation range required")
        if operation_kind not in ("discovery","evidence_review"):raise ValueError("unknown operation kind")
        node_id=self.f.policy.resolve(node_id)
        node=self.db.execute("SELECT * FROM discovery_nodes WHERE id=?",(node_id,)).fetchone()
        if node is None:raise ValueError("declare an actually observed discovery node")
        existing={r[0] for r in self.db.execute("SELECT action_id FROM discovery_epoch_actions WHERE epoch_id=?",(self.id,))}
        if action_id in existing or len(set(requires))!=len(requires) or not set(requires)<=existing:
            raise ValueError("new action identity and existing unique dependencies required")
        if initial:
            if revealed_by or requires or self.db.execute("SELECT 1 FROM discovery_epoch_actions WHERE epoch_id=? AND outcome IS NOT NULL LIMIT 1",(self.id,)).fetchone():
                raise ValueError("initial frontier must be declared before any recorded outcome")
        else:
            parent=self.db.execute("SELECT node_id,outcome FROM discovery_epoch_actions WHERE epoch_id=? AND action_id=?",(self.id,revealed_by)).fetchone()
            if not parent or parent[1] is not None:raise ValueError("declare revealed children before sealing their parent outcome")
            found=self.db.execute("""WITH RECURSIVE reach(id) AS (
                SELECT child FROM discovery_edges WHERE parent=? UNION
                SELECT e.child FROM discovery_edges e JOIN reach r ON e.parent=r.id)
                SELECT 1 FROM reach WHERE id=? LIMIT 1""",(parent[0],node_id)).fetchone()
            if not found:raise ValueError("revealed child requires an observed discovery path")
        if choice_seq is not None:
            choice=self.db.execute("SELECT node_id FROM discovery_choices WHERE seq=?",(choice_seq,)).fetchone()
            if not choice or choice[0]!=node_id or choice_seq<=context["choice_floor"]:
                raise ValueError("choice must identify this node in the current epoch")
        observed=json.loads(node["features"])
        f={"year":node["year"],"direct_evidence":bool(observed.get("direct_evidence",False)),
           "independent_family":False,"unprocessed":True,**(features or {})}
        if (set(f)!={"year","direct_evidence","independent_family","unprocessed"}
                or any(type(f[k]) is not bool for k in f if k!="year")
                or f["year"] is not None and (type(f["year"]) is not int or f["year"] not in YEARS)):
            raise ValueError("only observable typed pre-execution features may be declared")
        assets={"input":asset(input_path),"operator":asset(operator_path)}
        source_id=node["family"] if ID.fullmatch(node["family"]) else "family:"+digest(node["family"])
        plan={"id":action_id,"source_id":source_id,"artifact_id":"sha256:"+assets["input"]["sha256"],
              "locator":node["url"] or record_locator,"requires":list(requires),"features":f,"cost_bound":cost_bound,
              "coverage":{"input_sha256":assets["input"]["sha256"],"operator_revision":assets["operator"]["sha256"],
                          "record_locator":record_locator,"original_url":node["url"] or None,
                          "capture_or_edition":capture_or_edition}}
        floor=self.db.execute("SELECT coalesce(max(rowid),0) FROM discovery_batches").fetchone()[0]
        with self.db:
            self.db.execute("""INSERT INTO discovery_epoch_actions(epoch_id,action_id,node_id,plan,assets,
                parent_action,initial,declared_ns,batch_floor,choice_seq,operation_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (self.id,action_id,node_id,canonical(plan).decode(),canonical(assets).decode(),revealed_by,
                 int(initial),time.time_ns(),floor,choice_seq,operation_kind))
        return plan

    @staticmethod
    def _discovery_completion(actual,plan,receipt):
        operation=actual.get("operation")
        expected={"kind":"discovery","scope_id":plan["coverage"]["record_locator"],
                  "operator_sha256":plan["coverage"]["operator_revision"],
                  "input_sha256":plan["coverage"]["input_sha256"],"complete":True}
        if operation!=expected:raise ValueError("discovery completion must bind the predeclared executor, input and complete scope")
        outputs=actual.get("outputs")
        if isinstance(outputs,dict):outputs=[{"path":p,"sha256":h} for p,h in outputs.items()]
        if not isinstance(outputs,list) or not outputs:raise ValueError("discovery completion needs verifiable produced artifacts")
        for output in outputs:
            if not isinstance(output,dict) or not output.get("path") or not output.get("sha256"):
                raise ValueError("invalid discovery output identity")
            path=(receipt.parent/Path(output["path"])).resolve(strict=True)
            if sha(path)!=output["sha256"]:raise ValueError("discovery output bytes changed")

    def finish(self,action_id,execution_receipt,*,batch_id=None,reason=None):
        row=self.db.execute("SELECT * FROM discovery_epoch_actions WHERE epoch_id=? AND action_id=?",(self.id,action_id)).fetchone()
        if row is None:raise ValueError("declare the action before execution")
        verify_assets(json.loads(row["assets"]))
        receipt=Path(execution_receipt).resolve(strict=True)
        if receipt.stat().st_mtime_ns<row["declared_ns"]:raise ValueError("execution receipt predates the declared action")
        raw=receipt.read_bytes();execution_sha=hashlib.sha256(raw).hexdigest();actual=json.loads(raw)
        cost=checked_cost(actual.get("cost"));plan=json.loads(row["plan"])
        if any(cost[k]>plan["cost_bound"][k] for k in COSTS):raise ValueError("actual execution exceeded its declared reservation")
        records=[];state="incomplete";batch=None
        if batch_id:
            if row["operation_kind"]!="evidence_review":raise ValueError("a discovery-only operation cannot claim reviewed evidence")
            batch=self.db.execute("SELECT rowid AS ordinal,* FROM discovery_batches WHERE id=?",(batch_id,)).fetchone()
            if (not batch or batch["prior"] or not batch["complete"] or batch["node_id"]!=row["node_id"]
                    or batch["scope_id"]!=plan["coverage"]["record_locator"] or batch["ordinal"]<=row["batch_floor"]):
                raise ValueError("complete outcome needs a newly reviewed matching node and predeclared scope")
            if any(batch[k]!=cost[k] for k in COSTS):raise ValueError("execution and reviewed batch costs disagree")
            retained=self.db.execute("SELECT report,records_sha256 FROM discovery_batch_receipts WHERE batch_id=?",(batch_id,)).fetchone()
            if not retained or not retained[1]:
                raise ValueError("reimport the original settle output to retain individual evidence")
            if hashlib.sha256(retained[0].encode()).hexdigest()!=batch["receipt_sha"]:
                raise ValueError("retained settlement report changed")
            record_hash=hashlib.sha256()
            for (body,) in self.db.execute("SELECT record FROM discovery_reviewed_records WHERE batch_id=? ORDER BY hostname,year,evidence_id",(batch_id,)):
                record_hash.update(body.encode())
                r=json.loads(body)
                evidence_sha=r.get("source_sha256") or r.get("body_sha256") or r.get("evidence_sha256")
                if not isinstance(evidence_sha,str) or not re.fullmatch(r"[0-9a-f]{64}",evidence_sha):
                    raise ValueError("reviewed evidence needs its original source/body SHA-256 for replay")
                records.append({"hostname":r["hostname"],"year":r["year"],"evidence_id":r["evidence_id"],
                    "evidence_locator":r.get("record_locator") or "manifest:"+r["manifest_hash"]+":"+str(r["ordinal"]),
                    "evidence_sha256":evidence_sha,"adjudication":"qualified"})
            if record_hash.hexdigest()!=retained[1]:raise ValueError("retained individual evidence changed")
            state="complete"
        elif row["operation_kind"]=="discovery" and actual.get("operation",{}).get("complete") is True:
            self._discovery_completion(actual,plan,receipt)
            state="complete"
        elif not isinstance(reason,str) or not reason.strip():
            raise ValueError("executed but unreviewed scope needs an explicit incomplete reason")
        reveals=[r[0] for r in self.db.execute("SELECT action_id FROM discovery_epoch_actions WHERE epoch_id=? AND parent_action=? ORDER BY seq",(self.id,action_id))]
        sealed={"schema":"discovery-outcome-v1","action_id":action_id,"node_id":row["node_id"],
                "execution_sha256":execution_sha,"batch_id":batch_id,"state":state,"cost":cost,
                "operation_kind":row["operation_kind"],"execution_locator":str(receipt),
                "coverage":plan["coverage"],"records":records,"reveals":reveals,"reason":reason}
        outcome={"state":state,"receipt_locator":"receipts/"+digest(sealed)+".json",
                 "receipt_sha256":hashlib.sha256(canonical(sealed)).hexdigest(),
                 "cost":cost,"records":records,"reveals":reveals}
        if state=="incomplete":outcome["reason"]=reason
        if row["outcome"]:
            if json.loads(row["outcome"])!=outcome:raise ValueError("completed action receipt cannot be replaced")
            return outcome
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO discovery_execution_receipts VALUES(?,?)",(execution_sha,raw))
            self.db.execute("INSERT OR IGNORE INTO discovery_execution_receipts VALUES(?,?)",(outcome["receipt_sha256"],canonical(sealed)))
            self.db.execute("UPDATE discovery_epoch_actions SET outcome=?,execution_sha=? WHERE epoch_id=? AND action_id=?",
                            (canonical(outcome).decode(),execution_sha,self.id,action_id))
        return outcome

    def export(self,out,*,rsiforme_root,evaluate_policy=None):
        context=self.context();verify_assets(context["assets"])
        rows=self.db.execute("SELECT * FROM discovery_epoch_actions WHERE epoch_id=? ORDER BY seq",(self.id,)).fetchall()
        if not rows:raise ValueError("declare at least one real action")
        actions=[];universe=set()
        for row in rows:
            verify_assets(json.loads(row["assets"]))
            outcome=json.loads(row["outcome"]) if row["outcome"] else {"state":"unobserved","reason":"declared action has no execution outcome"}
            if row["operation_kind"]=="discovery" and outcome["state"]=="complete":
                sealed=json.loads(self.db.execute("SELECT bytes FROM discovery_execution_receipts WHERE sha=?",(outcome["receipt_sha256"],)).fetchone()[0])
                actual=json.loads(self.db.execute("SELECT bytes FROM discovery_execution_receipts WHERE sha=?",(row["execution_sha"],)).fetchone()[0])
                self._discovery_completion(actual,json.loads(row["plan"]),Path(sealed["execution_locator"]))
            actions.append({**json.loads(row["plan"]),"outcome":outcome})
            universe.update((r["hostname"],r["year"]) for r in outcome.get("records",[]))
        audit=Path(context["assets"]["audit"]["path"]);model=Path(context["assets"]["model"]["path"])
        authority,annual=audit_binding(audit,model)
        if authority!=context["authority"]:raise ValueError("frozen authority changed")
        targets={}
        for h,y in universe:targets.setdefault(y,set()).add(h)
        baseline_keys=[]
        # Read each relevant annual file once to EOF, validating its hash,
        # ordering and count. Other years cannot affect membership of K.
        # This avoids both per-action rescans and materializing full B in RAM.
        for y,hosts in sorted(targets.items()):
            for h in annual_stream(Path(context["baseline"])/f"{y}.txt",annual[y]):
                if h in hosts:baseline_keys.append({"hostname":h,"year":y})
        baseline_keys.sort(key=lambda row:(row["hostname"],row["year"]))
        reviewed_keys=[];reviewed_hash=hashlib.sha256()
        for h,y in self.db.execute("SELECT hostname,year FROM discovery_epoch_prior WHERE epoch_id=? ORDER BY hostname,year",(self.id,)):
            row={"hostname":h,"year":y};reviewed_hash.update(canonical(row))
            if (h,y) in universe:reviewed_keys.append(row)
        if reviewed_hash.hexdigest()!=context["reviewed_sha256"]:raise ValueError("frozen prior snapshot changed")
        fixed={}
        for tld,w in weights(model).items():
            units=w*10000
            if units!=units.to_integral_value():raise ValueError("model weights finer than 1/10000 EED")
            fixed[tld]=int(units)
        projection={"schema":"discovery-membership-projection-v1","authority":authority,
                    "reviewed_sha256":context["reviewed_sha256"],
                    "verified_baseline_years":sorted(targets),
                    "key_universe_sha256":digest([{"hostname":h,"year":y} for h,y in sorted(universe)]),
                    "baseline_keys":baseline_keys,"reviewed_keys":reviewed_keys,"complete":True}
        raw={"schema_version":1,"epoch_id":self.id,"data_kind":context["data_kind"],
             "source_bindings":{"baseline_sha256":digest(authority["annual_sha256"]),
                "reviewed_sha256":context["reviewed_sha256"],"rules_sha256":context["assets"]["rules"]["sha256"],
                "model_sha256":context["assets"]["model"]["sha256"]},
             "baseline_keys":baseline_keys,"reviewed_keys":reviewed_keys,"weights":fixed,"budget":context["budget"],
             "initial_frontier":[r["action_id"] for r in rows if r["initial"]],"actions":actions,
             "projection":{"key_universe_sha256":projection["key_universe_sha256"],"receipt_locator":"projection.json",
                "receipt_sha256":hashlib.sha256(canonical(projection)).hexdigest(),"complete":True}}
        root=Path(rsiforme_root).resolve(strict=True);out=Path(out).resolve()
        prepare=root/"examples/creeperman_replay/prepare.py"
        env={**os.environ,"PYTHONPATH":str(root/"src")}
        with new_output(out) as stage:
            (stage/"epoch.json").write_bytes(canonical(raw));(stage/"projection.json").write_bytes(canonical(projection))
            (stage/"receipts").mkdir();(stage/"execution").mkdir()
            for row in rows:
                if row["outcome"]:
                    outcome=json.loads(row["outcome"])
                    for key,path in ((outcome["receipt_sha256"],stage/outcome["receipt_locator"]),
                                     (row["execution_sha"],stage/"execution"/(row["execution_sha"]+".json"))):
                        stored=self.db.execute("SELECT bytes FROM discovery_execution_receipts WHERE sha=?",(key,)).fetchone()
                        if not stored or hashlib.sha256(stored[0]).hexdigest()!=key:raise ValueError("retained execution receipt changed")
                        path.write_bytes(stored[0])
            completed=subprocess.run([sys.executable,str(prepare),"--input",str(stage/"epoch.json"),"--output",str(stage/"prepared")],
                                     env=env,text=True,capture_output=True,timeout=120)
            if completed.returncode:raise ValueError("RSI prepare rejected exported epoch: "+completed.stderr[-2000:])
        result={"epoch_id":self.id,"out":str(out),"actions":len(actions),"data_kind":context["data_kind"],
                "universe_size":len(universe),"baseline_hits":len(baseline_keys),"prior_hits":len(reviewed_keys),
                "online_requests":0,"production_ledger_written":False}
        if evaluate_policy:
            execution=subprocess.run([sys.executable,str(prepare.with_name("run.py")),"--prepared",str(out/"prepared"),
                "--policy",str(Path(evaluate_policy).resolve()),"--store",str(out/"research")],env=env,text=True,capture_output=True,timeout=150)
            if execution.returncode not in (0,2):raise ValueError("RSI evaluation failed: "+execution.stderr[-2000:])
            evaluated=json.loads(execution.stdout);(out/"evaluation.json").write_bytes(canonical(evaluated))
            result["evaluation"]={k:evaluated["evaluation"][k] for k in ("id","valid","metrics","completion_reason")}
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--epoch-id",required=True);sub=parser.add_subparsers(dest="command",required=True)
    q=sub.add_parser("init")
    for k in ("baseline","audit","model","rules"):q.add_argument("--"+k,type=Path,required=True)
    q.add_argument("--budget",type=Path,required=True);q.add_argument("--data-kind",choices=("recorded","synthetic_fixture"),default="recorded")
    q=sub.add_parser("declare");q.add_argument("--plan",type=Path,required=True)
    q=sub.add_parser("finish");q.add_argument("--action-id",required=True);q.add_argument("--execution-receipt",type=Path,required=True)
    q.add_argument("--batch-id");q.add_argument("--reason")
    q=sub.add_parser("export");q.add_argument("--out",type=Path,required=True);q.add_argument("--rsiforme-root",type=Path,required=True)
    q.add_argument("--evaluate-policy",type=Path)
    args=vars(parser.parse_args(argv));db=args.pop("db");epoch=args.pop("epoch_id");command=args.pop("command")
    from .source_frontier import Frontier
    with collector_lock(db):
        f=Frontier(db)
        try:
            recorder=DiscoveryEpoch(f,epoch)
            if command=="init":args["budget"]=json.loads(args["budget"].read_text());result=recorder.initialize(**args)
            elif command=="declare":result=recorder.declare(**json.loads(args["plan"].read_text()))
            elif command=="finish":result=recorder.finish(**args)
            else:result=recorder.export(**args)
            print(canonical(result).decode(),end="")
        finally:f.close()


if __name__=="__main__":main()
