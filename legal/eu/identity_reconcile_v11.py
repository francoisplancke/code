from __future__ import annotations
import json,re,collections
from pathlib import Path
CELEX3=re.compile(r"^3(\d{4})([A-Z]{1,3})(\d{4,6})(?:\(\d{2}\))?(?:R\(\d{2}\))?$",re.I)
TYPE={"L":"DIRECTIVE","R":"REGULATION","D":"DECISION","H":"RECOMMENDATION","E":"CFSP","O":"ECB_GUIDELINE","F":"PJCC","Q":"INSTITUTIONAL","B":"BUDGET","S":"ECSC_DECISION"}

def latest(path):
 d={}
 for line in open(path,encoding="utf8"):
  if line.strip():
   x=json.loads(line); d[x["cellar_uuid"]]=x
 return d

def parse(c):
 m=CELEX3.fullmatch(c or "")
 if not m:return None
 return {"year":int(m[1]),"descriptor":m[2].upper(),"document_number":m[3],"act_type":TYPE.get(m[2].upper(),"OTHER")}

def celex_aliases(sp):
 out=[]
 for u in sp.get("same_as") or []:
  marker="/resource/celex/"
  if marker in u:
   from urllib.parse import unquote
   out.append(unquote(u.split(marker,1)[1]).upper())
 return sorted(set(out))

def reconcile(cid,o,s):
 os_,oc=o.get("status"),o.get("celex"); ss,sc=s.get("status"),s.get("celex")
 if ss=="RESOLVED":
  st,canon,src="RESOLVED",sc,"CELLAR_SPARQL_OWL_SAMEAS"
  if os_=="RESOLVED": cmp="SPARQL_CONFIRMS_FMX" if oc==sc else "SPARQL_CONTRADICTS_FMX"
  elif os_=="AMBIGUOUS":cmp="SPARQL_RESOLVES_FMX_AMBIGUOUS"
  else:cmp="SPARQL_RESOLVES_FMX_UNRESOLVED"
 elif ss in ("NO_SECTOR3_CELEX","NO_CELEX"):
  st,canon,src,cmp="OUT_OF_SCOPE_CELEX",None,None,"NO_SECTOR3_CELEX"
 elif ss=="MULTIPLE_CELEX":
  st,canon,src,cmp="AMBIGUOUS",None,None,"SPARQL_MULTIPLE_CELEX"
 elif ss=="SPARQL_ERROR":
  if os_=="RESOLVED":st,canon,src,cmp="RESOLVED_FALLBACK",oc,"FMX_FALLBACK_AFTER_SPARQL_ERROR","SPARQL_ERROR_FMX_FALLBACK"
  else:st,canon,src,cmp="UNRESOLVED",None,None,"SPARQL_ERROR_UNRESOLVED"
 else:
  st,canon,src,cmp="UNRESOLVED",None,None,"SPARQL_STATUS_UNKNOWN"
 p=parse(canon)
 return {"schema_version":"r7.0.2.2-v1.1","cellar_uuid":cid,"status":st,"celex":canon,"identity_source":src,
 "act_type":p["act_type"] if p else None,"year":p["year"] if p else None,"descriptor":p["descriptor"] if p else None,
 "document_number":p["document_number"] if p else None,"comparison":cmp,
 "sparql_status":ss,"sparql_celex":sc,"sparql_celex_candidates":s.get("celex_candidates") or [],
 "sparql_celex_aliases_all":celex_aliases(s),"same_as":s.get("same_as") or [],
 "offline_status":os_,"offline_celex":oc,"offline_method":o.get("method")}

def run(offline,sparql,out,summary,conflicts,outscope,duplicates):
 off=latest(offline);sp=latest(sparql);ids=sorted(set(off)|set(sp))
 statuses=collections.Counter();comps=collections.Counter();types=collections.Counter()
 by_celex=collections.defaultdict(list);uuid_multi=[]
 Path(out).parent.mkdir(parents=True,exist_ok=True)
 with open(out,"w",encoding="utf8") as fo,open(conflicts,"w",encoding="utf8") as fc,open(outscope,"w",encoding="utf8") as fx:
  for cid in ids:
   r=reconcile(cid,off.get(cid,{"status":"MISSING"}),sp.get(cid,{"status":"MISSING"}))
   fo.write(json.dumps(r,ensure_ascii=False)+"\n");statuses[r["status"]]+=1;comps[r["comparison"]]+=1
   if r["act_type"]:types[r["act_type"]]+=1
   if r["celex"]:by_celex[r["celex"]].append(cid)
   if len(r["sparql_celex_candidates"])>1:uuid_multi.append({"cellar_uuid":cid,"celex_candidates":r["sparql_celex_candidates"]})
   if r["comparison"]=="SPARQL_CONTRADICTS_FMX":fc.write(json.dumps(r,ensure_ascii=False)+"\n")
   if r["status"]=="OUT_OF_SCOPE_CELEX":fx.write(json.dumps(r,ensure_ascii=False)+"\n")
 celex_multi=[{"celex":c,"cellar_uuids":us,"count":len(us)} for c,us in sorted(by_celex.items()) if len(us)>1]
 with open(duplicates,"w",encoding="utf8") as f:
  for x in celex_multi:f.write(json.dumps({"kind":"CELEX_TO_MULTIPLE_CELLAR",**x},ensure_ascii=False)+"\n")
  for x in uuid_multi:f.write(json.dumps({"kind":"CELLAR_TO_MULTIPLE_CELEX",**x},ensure_ascii=False)+"\n")
 s={"schema_version":"r7.0.2.2-v1.1","objects":len(ids),"canonical_status":dict(statuses),"comparison":dict(comps),"act_types":dict(types),
 "identity_audit":{"conflicts":comps["SPARQL_CONTRADICTS_FMX"],"out_of_scope_celex":statuses["OUT_OF_SCOPE_CELEX"],
 "celex_to_multiple_cellar":len(celex_multi),"cellar_to_multiple_celex":len(uuid_multi)},
 "inputs":{"offline":str(offline),"sparql":str(sparql)},
 "outputs":{"canonical":str(out),"conflicts":str(conflicts),"out_of_scope":str(outscope),"duplicates":str(duplicates)}}
 Path(summary).write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf8");return s
