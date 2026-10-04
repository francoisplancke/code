import json,re,collections
from pathlib import Path
SCHEMA='r7.2.0-v1'
CORR=re.compile(r'^(?P<base>3\d{4}[A-Z]{1,3}\d{4,6}(?:\(\d{2}\))?)R\((?P<n>\d{2})\)$',re.I)
def rows(path):
 with open(path,encoding='utf8') as f:
  for line in f:
   if line.strip(): yield json.loads(line)
def parse_corrigendum(celex):
 m=CORR.match(celex or '')
 return None if not m else {'base_celex':m.group('base').upper(),'corrigendum_number':int(m.group('n'))}
def run(identity,provisions,out_dir):
 identities=list(rows(identity));by={x.get('celex'):x for x in identities if x.get('celex')};od=Path(out_dir);od.mkdir(parents=True,exist_ok=True)
 docs=[];rels=[];st=collections.Counter()
 for x in sorted(identities,key=lambda z:(z.get('celex') or '',z.get('cellar_uuid') or '')):
  celex=x.get('celex');c=parse_corrigendum(celex);kind='CORRIGENDUM' if c else 'BASE_OR_STANDALONE'
  d={'schema_version':SCHEMA,'celex':celex,'cellar_uuid':x.get('cellar_uuid'),'document_kind':kind,'act_type':x.get('act_type'),'identity_status':x.get('status'),'canonical_identity_source':x.get('canonical_source') or x.get('identity_source')}
  if c:
   target=by.get(c['base_celex']);rs='DERIVED_AND_TARGET_PRESENT' if target else 'DERIVED_TARGET_ABSENT';st[rs]+=1;d.update(c);d['base_target_status']=rs
   rels.append({'schema_version':SCHEMA,'relation_type':'CORRIGENDUM_OF','source_celex':celex,'source_cellar_uuid':x.get('cellar_uuid'),'target_celex':c['base_celex'],'target_cellar_uuid':target.get('cellar_uuid') if target else None,'corrigendum_number':c['corrigendum_number'],'derivation':'CELEX_SUFFIX_R_NN','status':rs})
  docs.append(d)
 src=list(rows(provisions));norm=[];pc=collections.Counter()
 for p in src:
  celex=p.get('celex');c=parse_corrigendum(celex);legal=c['base_celex'] if c else celex;q=dict(p)
  q.update({'normalization_schema':SCHEMA,'source_document_celex':celex,'legal_act_celex':legal,'source_document_kind':'CORRIGENDUM' if c else 'BASE_OR_STANDALONE','legal_act_target_present':legal in by if legal else False});norm.append(q);pc[q['source_document_kind']]+=1
 dp=od/'r7_2_0_documents.jsonl';rp=od/'r7_2_0_relations.jsonl';pp=od/'r7_2_0_provisions_normalized.jsonl';mp=od/'r7_2_0_missing_targets.jsonl';missing=[r for r in rels if r['status']=='DERIVED_TARGET_ABSENT']
 for path,data in [(dp,docs),(rp,rels),(pp,norm),(mp,missing)]:path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data),encoding='utf8')
 s={'schema_version':SCHEMA,'documents':len(docs),'corrigenda':len(rels),'relations':{'CORRIGENDUM_OF':len(rels)},'relation_status':dict(st),'provisions':len(norm),'provisions_by_source_document_kind':dict(pc),'missing_base_targets':len(missing),'invariants':{'one_relation_per_corrigendum':len(rels)==sum(d['document_kind']=='CORRIGENDUM' for d in docs),'provision_count_preserved':len(norm)==len(src),'provision_ids_preserved':all(a.get('provision_id')==b.get('provision_id') for a,b in zip(src,norm))},'outputs':{'documents':str(dp),'relations':str(rp),'normalized_provisions':str(pp),'missing_targets':str(mp)}}
 (od/'r7_2_0_summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return s
