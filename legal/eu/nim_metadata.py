from __future__ import annotations
import collections, hashlib, json, time, urllib.parse, urllib.request
from pathlib import Path
SCHEMA='r7.2.2-v1'; ENDPOINT='https://publications.europa.eu/webapi/rdf/sparql'
CDM='http://publications.europa.eu/ontology/cdm#'
P={
'nim_celex':CDM+'resource_legal_id_celex','title':CDM+'work_title','act_type':CDM+'measure_national_implementing_type_act',
'document_date':CDM+'work_date_document','notification_date':CDM+'measure_national_implementing_date_notification',
'official_journal_date':CDM+'measure_national_implementing_date_official_journal','official_journal_name':CDM+'measure_national_implementing_name_official_journal',
'official_journal_page':CDM+'measure_national_implementing_page_official_journal','commission_reference':CDM+'measure_national_implementing_reference_commission',
'member_state_reference':CDM+'measure_national_implementing_reference_member-state','national_local_id':CDM+'resource_legal_id_local',
'work_id_document':CDM+'work_id_document','eli':CDM+'eli'}
EXTRA=[CDM+'measure_national_implementing_implements_resource_legal',CDM+'measure_national_implementing_implements_directive','http://www.w3.org/2002/07/owl#sameAs']

def rows(p):
 with open(p,encoding='utf8') as f:
  for l in f:
   if l.strip(): yield json.loads(l)
def work(r):
 for k in ('nim_work','nim_uri','nim_work_uri','work','work_uri','cellar_uri'):
  v=r.get(k)
  if isinstance(v,str) and v.startswith(('http://','https://')): return v
 for k in ('nim_cellar_uuid','cellar_uuid'):
  if r.get(k): return 'http://publications.europa.eu/resource/cellar/'+r[k]
def fetch(endpoint,q,timeout=90):
 req=urllib.request.Request(endpoint,data=urllib.parse.urlencode({'query':q}).encode(),headers={'Accept':'application/sparql-results+json','Content-Type':'application/x-www-form-urlencoded','User-Agent':'legal-simplification-r7.2.2/1'})
 with urllib.request.urlopen(req,timeout=timeout) as x:return json.load(x)
def query(ws):
 vals=' '.join('<%s>'%x for x in ws); ps=' '.join('<%s>'%x for x in list(P.values())+EXTRA)
 return f'SELECT ?work ?p ?o WHERE {{ VALUES ?work {{ {vals} }} VALUES ?p {{ {ps} }} ?work ?p ?o . }} ORDER BY ?work ?p ?o'
def obj(x):
 o=x['o'];return {'value':o.get('value'),'type':o.get('type'),'lang':o.get('xml:lang'),'datatype':o.get('datatype')}
def run(inp,out_dir,batch_size=50,endpoint=ENDPOINT,retries=3,backoff=2.0,fetcher=fetch):
 src=list(rows(inp)); ws=sorted({w for r in src if (w:=work(r))}); od=Path(out_dir); cache=od/'cache';cache.mkdir(parents=True,exist_ok=True)
 raw=collections.defaultdict(lambda:collections.defaultdict(list)); failed=[]
 for i in range(0,len(ws),batch_size):
  b=ws[i:i+batch_size]; key=hashlib.sha256('\n'.join(b).encode()).hexdigest(); cp=cache/(key+'.json'); data=None
  if cp.exists(): data=json.loads(cp.read_text(encoding='utf8'))
  else:
   err=None
   for a in range(retries):
    try:data=fetcher(endpoint,query(b));cp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');break
    except Exception as e:
     err=repr(e)
     if a+1<retries:time.sleep(backoff*2**a)
   if data is None:failed.append({'works':b,'error':err});continue
  for x in data.get('results',{}).get('bindings',[]): raw[x['work']['value']][x['p']['value']].append(obj(x))
 inv={v:k for k,v in P.items()}; enriched=[]; coverage=collections.Counter(); ambiguous=collections.Counter()
 for w in ws:
  byp=raw.get(w,{}); r={'schema_version':SCHEMA,'nim_work':w,'fields':{},'relation_values':{},'raw_predicates':{}}
  for pred,vals in sorted(byp.items()):
   # exact de-duplication, deterministic
   uniq=[];seen=set()
   for v in vals:
    k=json.dumps(v,sort_keys=True,ensure_ascii=False)
    if k not in seen:seen.add(k);uniq.append(v)
   r['raw_predicates'][pred]=uniq
   if pred in inv:
    name=inv[pred]; strings=[v['value'] for v in uniq]; r['fields'][name]={'value':strings[0] if len(strings)==1 else None,'values':strings,'status':'UNIQUE' if len(strings)==1 else ('MISSING' if not strings else 'MULTIPLE')}
    if strings:coverage[name]+=1
    if len(strings)>1:ambiguous[name]+=1
   elif pred in EXTRA:r['relation_values'][pred]=[v['value'] for v in uniq]
  for name in P:
   if name not in r['fields']:r['fields'][name]={'value':None,'values':[],'status':'MISSING'}
  enriched.append(r)
 ep=od/'r7_2_2_nim_metadata.jsonl';ep.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in enriched),encoding='utf8')
 fp=od/'r7_2_2_failed_batches.jsonl';fp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in failed),encoding='utf8')
 # binding-ready flat view; ambiguous values are deliberately null canonically
 bp=od/'r7_2_2_binding_inputs.jsonl'
 flat=[]
 for r in enriched:
  q={'schema_version':SCHEMA,'nim_work':r['nim_work']}
  for name in P:q[name]=r['fields'][name]['value']
  q['ambiguous_fields']=[n for n in P if r['fields'][n]['status']=='MULTIPLE'];flat.append(q)
 bp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in flat),encoding='utf8')
 summary={'schema_version':SCHEMA,'distinct_nim_works':len(ws),'works_enriched':sum(bool(raw.get(w)) for w in ws),'failed_batches':len(failed),'field_coverage':{k:coverage[k] for k in P},'field_ambiguities':{k:ambiguous[k] for k in P if ambiguous[k]},'invariants':{'one_output_per_work':len(enriched)==len(ws),'no_silent_multivalue_collapse':all(not (f['status']=='MULTIPLE' and f['value'] is not None) for r in enriched for f in r['fields'].values())},'outputs':{'metadata':str(ep),'binding_inputs':str(bp),'failed_batches':str(fp),'cache':str(cache)}}
 (od/'r7_2_2_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return summary
