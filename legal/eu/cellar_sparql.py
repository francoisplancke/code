import json,re,time,urllib.parse,urllib.request,urllib.error,hashlib
from pathlib import Path
ENDPOINT="https://publications.europa.eu/webapi/rdf/sparql"; BASE="http://publications.europa.eu/resource/cellar/"; CB="http://publications.europa.eu/resource/celex/"
C3=re.compile(r"^3\d{4}[A-Z]{1,3}\d{4,6}(?:R\(\d{2}\))?$",re.I)
def uuids(p):
 seen=set()
 for l in open(p):
  if l.strip():
   u=json.loads(l)["cellar_uuid"]
   if u not in seen:seen.add(u);yield u
def query(xs):
 return "PREFIX owl:<http://www.w3.org/2002/07/owl#>\nSELECT DISTINCT ?work ?identifier WHERE { VALUES ?work { "+ " ".join("<"+BASE+x+">" for x in xs)+" } ?work owl:sameAs ?identifier . }"
def parse(data):
 d={}
 for b in json.loads(data)["results"]["bindings"]:
  w=b["work"]["value"];i=b["identifier"]["value"]
  if w.startswith(BASE):d.setdefault(w[len(BASE):],[]).append(i)
 return d
def classify(u,ids):
 cs=sorted({x[len(CB):].upper() for x in ids if x.startswith(CB) and C3.match(x[len(CB):])})
 s="RESOLVED" if len(cs)==1 else "MULTIPLE_CELEX" if len(cs)>1 else "NO_CELEX"
 return {"schema_version":"r7.0.2.1-v2","cellar_uuid":u,"source":"CELLAR_SPARQL_OWL_SAMEAS","status":s,"celex":cs[0] if len(cs)==1 else None,"celex_candidates":cs,"same_as":sorted(set(ids))}
class Client:
 def __init__(self,cache,timeout=60,retries=4,interval=.5):
  self.c=Path(cache);self.c.mkdir(parents=True,exist_ok=True);self.t=timeout;self.r=retries;self.i=interval;self.last=0
 def get(self,xs):
  p=self.c/(hashlib.sha256("\n".join(xs).encode()).hexdigest()+".json")
  if p.exists():return p.read_bytes(),"CACHE"
  body=urllib.parse.urlencode({"query":query(xs)}).encode()
  for a in range(self.r+1):
   time.sleep(max(0,self.i-(time.monotonic()-self.last)))
   req=urllib.request.Request(ENDPOINT,data=body,headers={"Accept":"application/sparql-results+json","Content-Type":"application/x-www-form-urlencoded","User-Agent":"legal-r7/2"})
   try:
    self.last=time.monotonic()
    with urllib.request.urlopen(req,timeout=self.t) as z:data=z.read()
    json.loads(data);tmp=p.with_suffix(".tmp");tmp.write_bytes(data);tmp.replace(p);return data,"NETWORK"
   except Exception as e:
    if a==self.r:raise
    time.sleep(min(16,2**a))
def split(c,xs):
 try:
  data,src=c.get(xs);m=parse(data);return [(u,m.get(u,[]),src,None) for u in xs]
 except Exception as e:
  if len(xs)==1:return [(xs[0],[],"ERROR",type(e).__name__+": "+str(e))]
  n=len(xs)//2;return split(c,xs[:n])+split(c,xs[n:])
def latest(p):
 d={};p=Path(p)
 if p.exists():
  for l in p.read_text().splitlines():
   try:x=json.loads(l);d[x["cellar_uuid"]]=x
   except:pass
 return d
def run(inp,out,cache,batch=250,limit=None):
 old=latest(out);todo=[u for u in uuids(inp) if u not in old or old[u].get("status")=="SPARQL_ERROR"]
 if limit is not None:todo=todo[:limit]
 c=Client(cache);cnt={}
 with open(out,"a") as f:
  for n in range(0,len(todo),batch):
   for u,ids,src,err in split(c,todo[n:n+batch]):
    x=classify(u,ids) if not err else {"schema_version":"r7.0.2.1-v2","cellar_uuid":u,"source":"CELLAR_SPARQL_OWL_SAMEAS","status":"SPARQL_ERROR","error":err}
    x["transport"]=src;f.write(json.dumps(x)+"\n");f.flush();cnt[x["status"]]=cnt.get(x["status"],0)+1
 return {"schema_version":"r7.0.2.1-v2","processed_this_run":len(todo),"resume_skipped":len(old),"status_this_run":cnt,"batch_size":batch}
