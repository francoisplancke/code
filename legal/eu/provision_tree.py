from __future__ import annotations
import json, re, hashlib, zipfile, collections
from pathlib import Path
from xml.etree import ElementTree as ET

SCHEMA="r7.1.2-v1"
QUOTE_TAGS={"QUOT.S"}
BLOCK_TAGS={"P","TXT","HT","TI","STI","TI.ART","STI.ART"}
ANNEX_BLOCKS={"P","NP","LIST","TBL","GR.SEQ","GR.TBL","TITLE","INCL.ELEMENT"}

def tag(e): return e.tag.rsplit("}",1)[-1] if "}" in e.tag else e.tag
def norm(s): return re.sub(r"\s+"," ",s or "").strip()
def text(e): return norm(" ".join(e.itertext()))
def direct_child(e,n):
 for c in e:
  if tag(c)==n:return c
 return None
def child_text(e,n):
 c=direct_child(e,n); return text(c) if c is not None else None

def load_directives(path):
 d={}
 for line in open(path,encoding="utf8"):
  if line.strip():
   x=json.loads(line)
   if x.get("status")=="RESOLVED" and x.get("act_type")=="DIRECTIVE":d[x["cellar_uuid"]]=x["celex"]
 return d

def load_members(path,wanted):
 d=collections.defaultdict(list)
 for line in open(path,encoding="utf8"):
  if line.strip():
   x=json.loads(line)
   if x.get("cellar_uuid") in wanted and x.get("member","").lower().endswith(".xml"):
    d[x["cellar_uuid"]].append(x)
 return d

def stable_id(celex,member,kind,path):
 return hashlib.sha256(f"{celex}|{member}|{kind}|{path}".encode()).hexdigest()[:24]

def has_quote_ancestor(path_tags): return any(x in QUOTE_TAGS for x in path_tags)

def visible_text(e):
 # Preserve textual content but remove quoted legal structures from the current provision's own text.
 parts=[]
 def walk(x,quoted=False):
  q=quoted or tag(x) in QUOTE_TAGS
  if not q and x.text:parts.append(x.text)
  for c in x:
   walk(c,q)
   if not q and c.tail:parts.append(c.tail)
 walk(e)
 return norm(" ".join(parts))

def division_label(e):
 return child_text(e,"TITLE") or child_text(e,"TI") or child_text(e,"NP") or ""

class Extractor:
 def __init__(self,celex,uuid,member):
  self.celex,self.uuid,self.member=celex,uuid,member;self.rows=[];self.warnings=[];self.ordinal=0
 def add(self,kind,path,parent=None,**kw):
  self.ordinal+=1
  r={"schema_version":SCHEMA,"provision_id":stable_id(self.celex,self.member,kind,path),
     "celex":self.celex,"cellar_uuid":self.uuid,"kind":kind,"parent_id":parent,
     "ordinal":self.ordinal,"fmx_member":self.member,"xml_path":path,**kw}
  self.rows.append(r);return r["provision_id"]
 def article(self,a,path,divs):
  label=child_text(a,"TI.ART") or child_text(a,"NO.ART") or child_text(a,"TI") or ""
  aid=self.add("ARTICLE",path,article_label=label,paragraph_label=None,list_path=[],
               division_path=divs,heading=child_text(a,"STI.ART"),text=visible_text(a))
  paras=[c for c in a if tag(c)=="PARAG"]
  alins=[c for c in a if tag(c)=="ALINEA"]
  if paras:
   for i,p in enumerate(paras,1):self.paragraph(p,f"{path}/PARAG[{i}]",aid,label,divs)
  for i,al in enumerate(alins,1):self.alinea(al,f"{path}/ALINEA[{i}]",aid,label,None,divs,[])
 def paragraph(self,p,path,parent,article_label,divs):
  pl=child_text(p,"NO.PARAG") or ""
  pid=self.add("PARAGRAPH",path,parent,article_label=article_label,paragraph_label=pl,
               list_path=[],division_path=divs,heading=None,text=visible_text(p))
  for i,al in enumerate([c for c in p if tag(c)=="ALINEA"],1):
   self.alinea(al,f"{path}/ALINEA[{i}]",pid,article_label,pl,divs,[])
 def alinea(self,a,path,parent,article_label,pl,divs,list_path):
  aid=self.add("ALINEA",path,parent,article_label=article_label,paragraph_label=pl,
               list_path=list_path,division_path=divs,heading=None,text=visible_text(a))
  for i,l in enumerate([c for c in a if tag(c)=="LIST"],1):
   self.list_(l,f"{path}/LIST[{i}]",aid,article_label,pl,divs,list_path)
 def list_(self,l,path,parent,article_label,pl,divs,prefix):
  for i,item in enumerate([c for c in l if tag(c)=="ITEM"],1):
   ip=f"{path}/ITEM[{i}]"; np=direct_child(item,"NP")
   marker=(child_text(np,"NO.P") if np is not None else None) or str(i)
   lp=prefix+[marker]
   iid=self.add("LIST_ITEM",ip,parent,article_label=article_label,paragraph_label=pl,
                list_path=lp,division_path=divs,heading=None,text=visible_text(item))
   # Lists may occur under NP/P/TXT; recurse while excluding QUOT.S.
   def scan(x,xp,quoted=False):
    q=quoted or tag(x) in QUOTE_TAGS
    if q:return
    counts=collections.Counter()
    for c in x:
     t=tag(c);counts[t]+=1;cp=f"{xp}/{t}[{counts[t]}]"
     if t=="LIST":self.list_(c,cp,iid,article_label,pl,divs,lp)
     else:scan(c,cp,q)
   scan(item,ip)
 def enact(self,en,path="ACT/ENACTING.TERMS",divs=None):
  divs=divs or [];counts=collections.Counter()
  for c in en:
   t=tag(c);counts[t]+=1;cp=f"{path}/{t}[{counts[t]}]"
   if t=="ARTICLE":self.article(c,cp,divs)
   elif t=="DIVISION":
    lbl=division_label(c);self.enact(c,cp,divs+[lbl])
 def annex(self,root,path):
  contents=direct_child(root,"CONTENTS")
  if contents is None:
   self.warnings.append({"code":"ANNEX_NO_CONTENTS","path":path});return
  aid=self.add("ANNEX",path,article_label=None,paragraph_label=None,list_path=[],
               division_path=[],heading=child_text(root,"TITLE"),text=visible_text(contents))
  counts=collections.Counter()
  for c in contents:
   t=tag(c);counts[t]+=1
   if t in ANNEX_BLOCKS:
    cp=f"{path}/CONTENTS/{t}[{counts[t]}]"
    self.add("ANNEX_BLOCK",cp,aid,article_label=None,paragraph_label=None,list_path=[],
             division_path=[],heading=child_text(c,"TITLE"),text=visible_text(c),fmx_tag=t)

def extract_xml(data,celex,uuid,member):
 root=ET.fromstring(data);rt=tag(root);x=Extractor(celex,uuid,member)
 if rt=="ACT":
  en=direct_child(root,"ENACTING.TERMS")
  if en is None:x.warnings.append({"code":"ACT_NO_ENACTING_TERMS","path":"ACT"})
  else:x.enact(en)
 elif rt=="ANNEX":x.annex(root,"ANNEX")
 return x.rows,x.warnings,rt

def run(zip_path,identity,inventory,out_dir,limit=None):
 ds=load_directives(identity);ids=sorted(ds)
 if limit is not None:ids=ids[:limit]
 ms=load_members(inventory,set(ids));od=Path(out_dir);od.mkdir(parents=True,exist_ok=True)
 po=od/"r7_1_2_provisions.jsonl";wo=od/"r7_1_2_warnings.jsonl"
 kinds=collections.Counter();roots=collections.Counter();warnings=[];errors=[];acts=collections.Counter()
 with zipfile.ZipFile(zip_path,allowZip64=True) as z,po.open("w",encoding="utf8") as pf:
  for u in ids:
   # Parse ACT and ANNEX roots only; TOC/DOC/CORR cannot create provisions.
   candidates=[m for m in ms.get(u,[]) if m.get("root_tag") in ("ACT","ANNEX")]
   for m in candidates:
    try:
     rows,ws,rt=extract_xml(z.read(m["member"]),ds[u],u,m["member"]);roots[rt]+=1
     for r in rows:pf.write(json.dumps(r,ensure_ascii=False)+"\n");kinds[r["kind"]]+=1
     acts[(u,rt)]+=len(rows)
     for w in ws:warnings.append({"cellar_uuid":u,"celex":ds[u],"member":m["member"],**w})
    except Exception as e:errors.append({"cellar_uuid":u,"celex":ds[u],"member":m["member"],"error":type(e).__name__+": "+str(e)})
 wo.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in warnings),encoding="utf8")
 (od/"r7_1_2_errors.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in errors),encoding="utf8")
 summary={"schema_version":SCHEMA,"directives_selected":len(ids),"directives_with_inventory_members":sum(u in ms for u in ids),
  "root_documents_parsed":dict(roots),"provisions":sum(kinds.values()),"kinds":dict(kinds),
  "warnings":len(warnings),"parse_errors":len(errors),
  "directives_with_act_provisions":len({u for (u,r),n in acts.items() if r=="ACT" and n}),
  "outputs":{"provisions":str(po),"warnings":str(wo),"errors":str(od/"r7_1_2_errors.jsonl")}}
 (od/"r7_1_2_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 return summary
