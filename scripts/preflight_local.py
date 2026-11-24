"""Bind a real task package without changing or publishing its contents.

Run locally. Verify the known task/model identity, then build a source
manifest for a single joint census. Full annual byte checks are deferred to
census, which reads them once to EOF. No network calls.
"""
import argparse
import json
from pathlib import Path
from creeperman.core import YEARS, audit_binding, sha, write_json

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--task-root",type=Path,required=True)
    p.add_argument("--audit",type=Path,default=Path("audit/baseline_summary.json"))
    p.add_argument("--extra-sources",type=Path)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    root=a.task_root.resolve()
    audit=json.loads(a.audit.read_text(encoding="utf-8"))
    baseline=root/audit["baseline"]
    model=root/"equivalent_english_domain_calculator/q2_tld_top_langs.json"
    binding,rows=audit_binding(a.audit,model)
    if not (root/"Internet_Digital_Ark_Project_1020_Update.docx").is_file():
        raise FileNotFoundError("current rules document missing")
    for y in YEARS:
        annual=baseline/f"{y}.txt"
        if not annual.is_file():raise FileNotFoundError(annual)
        if "bytes" in rows[y] and annual.stat().st_size!=rows[y]["bytes"]:
            raise ValueError(f"annual file size mismatch: {annual}")
    pool=baseline/"candidate_pool.txt"
    if not pool.is_file():raise FileNotFoundError(pool)
    sources=[{"source_id":"official-candidate-pool","origin_family":"competition-pool",
              "role":"existing_pool","format":"hosts","path":str(pool),"sha256":sha(pool),
              "allowed_by_competition":True}]
    cfg={}
    if a.extra_sources:
        cfg=json.loads(a.extra_sources.read_text(encoding="utf-8"))
        for x in cfg["sources"]:
            if x.get("allowed_by_competition") is not True:raise ValueError("source approval required")
            item=dict(x);path=(a.extra_sources.parent/item["path"]).resolve()
            item["path"]=str(path)
            digest=sha(path)
            if item.get("sha256") and item["sha256"]!=digest:raise ValueError(f"source changed: {path}")
            item["sha256"]=digest;sources.append(item)
        if cfg.get("local_qualified"):
            local=dict(cfg["local_qualified"])
            local["path"]=str((a.extra_sources.parent/local["path"]).resolve())
            cfg["local_qualified"]=local
    cfg["sources"]=sources
    a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.out.exists():raise FileExistsError(a.out)
    write_json(a.out,cfg)
    print(json.dumps({"authority":binding,"baseline":str(baseline),"model":str(model),
        "sources":str(a.out.resolve()),"rule_file_sha256":sha(root/"Internet_Digital_Ark_Project_1020_Update.docx"),
        "scope":"preflight only; annual full hashes checked by census"},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
