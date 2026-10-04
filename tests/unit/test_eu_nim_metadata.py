import json
from legal.eu.nim_metadata import run,P
def wr(p,x):p.write_text(''.join(json.dumps(i)+'\n' for i in x))
def fake(endpoint,q):
 ws=[x for x in ('http://x/a','http://x/b') if '<'+x+'>' in q];b=[]
 for w in ws:
  def add(p,v,typ='literal'):b.append({'work':{'value':w},'p':{'value':p},'o':{'value':v,'type':typ}})
  add(P['title'],'Titre '+w[-1]);add(P['document_date'],'2020-01-01');add(P['nim_celex'],'72020L0001FRA_'+w[-1])
  if w.endswith('a'):add(P['national_local_id'],'ID1');add(P['national_local_id'],'ID2')
 return {'results':{'bindings':b}}
def test_projection_and_ambiguity(tmp_path):
 i=tmp_path/'i';o=tmp_path/'o';wr(i,[{'nim_work':'http://x/a'},{'nim_work':'http://x/b'},{'nim_work':'http://x/a'}]);s=run(i,o,1,fetcher=fake)
 assert s['distinct_nim_works']==2 and s['field_coverage']['title']==2 and s['field_ambiguities']['national_local_id']==1
 rows=[json.loads(x) for x in (o/'r7_2_2_nim_metadata.jsonl').read_text().splitlines()];a=next(x for x in rows if x['nim_work'].endswith('a'))
 assert a['fields']['national_local_id']['status']=='MULTIPLE' and a['fields']['national_local_id']['value'] is None
def test_binding_flat(tmp_path):
 i=tmp_path/'i';o=tmp_path/'o';wr(i,[{'nim_work':'http://x/b'}]);run(i,o,50,fetcher=fake);x=json.loads((o/'r7_2_2_binding_inputs.jsonl').read_text());assert x['title']=='Titre b' and x['document_date']=='2020-01-01'
