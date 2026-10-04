from __future__ import annotations
import json
from pathlib import Path
from .celex import sector3_from_aliases,decode_celex_resource
def classify(cellar_uuid,ids):
 cs=sector3_from_aliases(ids)
 status="RESOLVED" if len(cs)==1 else "MULTIPLE_CELEX" if len(cs)>1 else "NO_SECTOR3_CELEX"
 return {"schema_version":"r7.0.2.1-v2.1","cellar_uuid":cellar_uuid,
 "source":"CELLAR_SPARQL_OWL_SAMEAS","status":status,
 "celex":cs[0] if len(cs)==1 else None,"celex_candidates":cs,
 "same_as":sorted(set(ids or [])),
 "celex_aliases_decoded":sorted(set(x for x in (decode_celex_resource(u) for u in ids or []) if x))}
def reclassify(inp,out,summary):
 counts={};total=0
 Path(out).parent.mkdir(parents=True,exist_ok=True)
 with open(inp,encoding="utf8") as src,open(out,"w",encoding="utf8") as dst:
  for line in src:
   if not line.strip():continue
   old=json.loads(line);total+=1
   # Preserve transport/provenance; only reclassify records for which same_as evidence exists.
   if old.get("status")=="SPARQL_ERROR":
    new=dict(old);new["schema_version"]="r7.0.2.1-v2.1"
   else:
    new=classify(old["cellar_uuid"],old.get("same_as") or [])
    if "transport" in old:new["transport"]=old["transport"]
   counts[new["status"]]=counts.get(new["status"],0)+1
   dst.write(json.dumps(new,ensure_ascii=False)+"\n")
 s={"schema_version":"r7.0.2.1-v2.1","objects":total,"status":counts,
    "input":str(inp),"output":str(out),"network_requests":0}
 Path(summary).write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 return s
