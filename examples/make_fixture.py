"""Generate a deliberately small SYNTHETIC authority and source manifest."""
import json
import sys
from decimal import Decimal
from pathlib import Path
from creeperman.core import YEARS, bit, canonical, sha, weights, write_json


def make(root: Path):
    root.mkdir(parents=True,exist_ok=False)
    base=root/"synthetic-baseline"
    base.mkdir()
    model=root/"model.json"
    write_json(model,{"tld":["com","org","uk"],"lang":["eng"]*3,
                      "perc_of_tld":["63.21","71.01","98.13"]})
    w=weights(model)
    annual=[]
    total=Decimal(0)
    for y in YEARS:
        hs={"same.org"}
        if y in {1996,1998}: hs.add("example.com")
        if y==1996: hs.add("www.example.com")
        p=base/f"{y}.txt"
        p.write_text("\n".join(sorted(hs))+"\n",encoding="ascii")
        e=sum((w[h.rsplit(".",1)[1]] for h in hs),Decimal(0))
        total+=e
        annual.append({"year":y,"sha256":sha(p),"status":"OK",
                       "normalized_order_inversions":0,"unique_valid_domains":len(hs)})
    audit=root/"audit.json"
    write_json(audit,{"baseline":base.name,"model_sha256":sha(model),
                "years":annual,"core_total":{"equivalent_english_domains":str(total)}})
    a=root/"source-a.jsonl"
    rows=[
        {"hostname":"example.com","original_url":"http://example.com/history","observed_year":1997},
        {"hostname":"www.example.com","observed_year":1996},
        {"hostname":"new.com","original_url":"http://new.com/","observed_year":1998},
        {"hostname":"new.com","observed_year":1999},
        {"hostname":"unknown.uk"},
        {"hostname":"late.uk","observed_year":2009},
        {"hostname":"same.org","observed_year":1998},
        {"hostname":"www.com"},
    ]
    a.write_bytes(b"".join(canonical(r) for r in rows))
    b=root/"source-b.jsonl"
    b.write_bytes(b"".join(canonical(r) for r in [
        {"hostname":"new.com","observed_year":1999},
        {"hostname":"a.new.com","observed_year":1998},
        {"hostname":"example.com","observed_year":1997}]))
    pool=root/"pool.txt"
    pool.write_text("new.com\npool-only.uk\n",encoding="ascii")
    sources=root/"sources.json"
    write_json(sources,{"sources":[
        {"source_id":"a","origin_family":"synthetic-A","format":"observations","path":a.name,"sha256":sha(a),"allowed_by_competition":True},
        {"source_id":"b","origin_family":"synthetic-B","format":"observations","path":b.name,"sha256":sha(b),"allowed_by_competition":True},
        {"source_id":"pool","origin_family":"synthetic-pool","role":"existing_pool","format":"hosts","path":pool.name,"sha256":sha(pool),"allowed_by_competition":True}]})
    return base,audit,model,sources


if __name__=="__main__":
    make(Path(sys.argv[1]))
