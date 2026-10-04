import collections,json,re
S3=re.compile(r"^3(\d{4})([A-Z]{1,3})(\d{4,6})(R\(\d{2}\))?$",re.I)
T={"L":"DIRECTIVE","R":"REGULATION","D":"DECISION","A":"OPINION","H":"RECOMMENDATION","G":"RESOLUTION","B":"BUDGET","C":"DECLARATION","E":"CFSP","F":"PJCC","K":"ECSC_RECOMMENDATION","M":"CONCENTRATION","O":"ECB_GUIDELINE","Q":"INSTITUTIONAL","S":"ECSC_DECISION","X":"OTHER_OJ_L"}
def parse(c):
 m=S3.match((c or "").upper())
 return None if not m else {"celex":c.upper(),"year":int(m[1]),"descriptor":m[2].upper(),"number":m[3],"corrigendum":m[4],"act_type":T.get(m[2].upper(),"OTHER")}
def resolve(cid,rows):
 cs=collections.defaultdict(list);elis=set()
 for x in rows:
  elis.update(x.get("eli") or [])
  for c in x.get("celex") or []:
   if parse(c):cs[c.upper()].append(x)
 ranked=[]
 for c,rr in cs.items():
  ev=[];score=0
  for x in rr:
   w=5 if x.get("role")=="DOC" else 4 if x.get("role")=="TOC" else 2 if x.get("role")=="FMX" else 1
   if x.get("root_tag") in ("DOC","PUBLICATION"):w+=2
   score+=w;ev.append({"member":x.get("member"),"role":x.get("role"),"root_tag":x.get("root_tag"),"weight":w})
  ranked.append({"celex":c,"score":score,"parsed":parse(c),"evidence":ev})
 ranked.sort(key=lambda x:(-x["score"],x["celex"]))
 status="UNRESOLVED";method=None;chosen=None;conf=0.;reasons=[]
 if not ranked:reasons=["NO_SECTOR3_CELEX_CANDIDATE"]
 else:
  a=ranked[0];b=ranked[1] if len(ranked)>1 else None
  strong=any(e["role"] in ("DOC","TOC") or e["root_tag"] in ("DOC","PUBLICATION") for e in a["evidence"])
  margin=a["score"]-(b["score"] if b else 0)
  if strong and (b is None or margin>=4):
   status="RESOLVED";method="STRUCTURED_FMX_CELEX";chosen=a["celex"];conf=.99 if b is None else min(.98,.8+.03*margin)
  elif len(ranked)==1:
   status="AMBIGUOUS";method="UNIQUE_BODY_CELEX";conf=.55;reasons=["IDENTITY_NOT_STRUCTURALLY_PROVEN"]
  else:
   status="AMBIGUOUS";method="MULTIPLE_CELEX_CANDIDATES";reasons=["MULTIPLE_PLAUSIBLE_SECTOR3_CELEX"]
 p=parse(chosen) if chosen else None
 return {"schema_version":"r7.0.2-v1","cellar_uuid":cid,"status":status,"method":method,"confidence":conf,"celex":chosen,
 "act_type":p["act_type"] if p else None,"year":p["year"] if p else None,"descriptor":p["descriptor"] if p else None,
 "document_number":p["number"] if p else None,"eli_candidates":sorted(elis),"candidate_count":len(ranked),"candidates":ranked[:20],"reasons":reasons}
def resolve_jsonl(inp,out,summary=None):
 g=collections.defaultdict(list)
 for l in open(inp,encoding="utf8"):
  if l.strip():
   x=json.loads(l);g[x["cellar_uuid"]].append(x)
 st=collections.Counter();me=collections.Counter();ty=collections.Counter()
 with open(out,"w",encoding="utf8") as f:
  for cid in sorted(g):
   x=resolve(cid,g[cid]);f.write(json.dumps(x,ensure_ascii=False)+"\n");st[x["status"]]+=1;me[x["method"] or "<NONE>"]+=1
   if x["act_type"]:ty[x["act_type"]]+=1
 s={"schema_version":"r7.0.2-v1","objects":len(g),"status":dict(st),"methods":dict(me),"act_types":dict(ty),"input":str(inp),"output":str(out)}
 if summary:open(summary,"w",encoding="utf8").write(json.dumps(s,ensure_ascii=False,indent=2)+"\n")
 return s
