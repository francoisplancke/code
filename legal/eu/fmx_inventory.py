import collections,json,re,zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
CELEX=re.compile(r"\b[0-9][0-9]{4}[A-Z][0-9]{3,5}\b",re.I)
ELI=re.compile(r"https?://data\.europa\.eu/eli/[^\s<>\"']+",re.I)
def local(t):return t.rsplit("}",1)[-1]
def role(n):
 n=n.lower()
 return "TOC" if n.endswith(".toc.fmx.xml") else "DOC" if n.endswith(".doc.xml") else "FMX" if n.endswith(".fmx.xml") else "XML"
def scan(z,zi):
 r={"cellar_uuid":PurePosixPath(zi.filename).parts[0],"member":zi.filename,"role":role(zi.filename),"root_tag":None,
 "compressed_bytes":zi.compress_size,"uncompressed_bytes":zi.file_size,"article_count":0,"paragraph_count":0,"point_count":0,
 "tags":{},"celex":[],"eli":[],"identifiers":[],"parse_error":None};tags=collections.Counter();cx=set();el=set()
 try:
  with z.open(zi) as f:
   for ev,e in ET.iterparse(f,events=("start","end")):
    t=local(e.tag)
    if ev=="start":
     if r["root_tag"] is None:r["root_tag"]=t
     tags[t]+=1;r["article_count"]+=t=="ARTICLE";r["paragraph_count"]+=t in ("PARAG","PARAGRAPH");r["point_count"]+=t=="POINT"
     for k,v in e.attrib.items():
      cx.update(x.upper() for x in CELEX.findall(str(v)));el.update(ELI.findall(str(v)))
      if len(r["identifiers"])<30 and any(q in local(k).upper() for q in ("ID","REF","CELEX","ELI")):r["identifiers"].append({"tag":t,"attribute":local(k),"value":str(v)[:500]})
    else:
     s=(e.text or "").strip()
     if s:cx.update(x.upper() for x in CELEX.findall(s));el.update(ELI.findall(s))
     e.clear()
 except Exception as e:r["parse_error"]=f"{type(e).__name__}: {e}"
 r["tags"]=dict(tags);r["celex"]=sorted(cx);r["eli"]=sorted(el);return r
def inventory(zp,out,summary=None,limit=None):
 ag={};roots=collections.Counter();roles=collections.Counter();errs=n=0
 with zipfile.ZipFile(zp,"r",allowZip64=True) as z,open(out,"w",encoding="utf8") as f:
  for zi in z.infolist():
   if zi.is_dir() or not zi.filename.lower().endswith(".xml"):continue
   r=scan(z,zi);f.write(json.dumps(r,ensure_ascii=False)+"\n");n+=1;roots[r["root_tag"] or "<ERROR>"]+=1;roles[r["role"]]+=1;errs+=bool(r["parse_error"])
   a=ag.setdefault(r["cellar_uuid"],{"cellar_uuid":r["cellar_uuid"],"xml_files":0,"roles":collections.Counter(),"roots":collections.Counter(),"uncompressed_xml_bytes":0,"article_count":0,"paragraph_count":0,"point_count":0,"celex":set(),"eli":set(),"parse_errors":0})
   a["xml_files"]+=1;a["roles"][r["role"]]+=1;a["roots"][r["root_tag"] or "<ERROR>"]+=1;a["uncompressed_xml_bytes"]+=r["uncompressed_bytes"]
   for k in ("article_count","paragraph_count","point_count"):a[k]+=r[k]
   a["celex"].update(r["celex"]);a["eli"].update(r["eli"]);a["parse_errors"]+=bool(r["parse_error"])
   if limit and n>=limit:break
 cp=str(out)+".cellar.jsonl"
 with open(cp,"w",encoding="utf8") as f:
  for a in ag.values():
   a["roles"]=dict(a["roles"]);a["roots"]=dict(a["roots"]);a["celex"]=sorted(a["celex"]);a["eli"]=sorted(a["eli"]);f.write(json.dumps(a,ensure_ascii=False)+"\n")
 s={"schema_version":"r7.0.1-v1","zip":str(zp),"xml_files":n,"cellar_objects":len(ag),"parse_errors":errs,"root_tags":dict(roots),"roles":dict(roles),"xml_jsonl":str(out),"cellar_jsonl":cp}
 if summary:open(summary,"w",encoding="utf8").write(json.dumps(s,ensure_ascii=False,indent=2))
 return s
