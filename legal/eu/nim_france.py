from __future__ import annotations
import hashlib,json,re,time,urllib.parse,urllib.request
from pathlib import Path
from collections import Counter,defaultdict

SCHEMA='r7.2.1-v1'
ENDPOINT='https://publications.europa.eu/webapi/rdf/sparql'
CELEX_URI='http://publications.europa.eu/resource/celex/'
NIM_RE=re.compile(r'^7(?P<year>\d{4})(?P<descriptor>[A-Z])(?P<number>\d{4,6})FRA_(?P<id>\d+)$',re.I)
STAR_RE=re.compile(r'^7\*FRA_(?P<id>\d+)$',re.I)

def rows(path):
    with open(path,encoding='utf8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def directive_celexes(path):
    out=[]
    for x in rows(path):
        if x.get('status')=='RESOLVED' and x.get('act_type')=='DIRECTIVE' and x.get('celex'):
            # NIM belongs to the legal base act, not to a corrigendum document.
            if 'R(' not in x['celex']: out.append(x['celex'].upper())
    return sorted(set(out))

def sparql(batch):
    vals=' '.join(f'<{CELEX_URI}{c}>' for c in batch)
    return f'''PREFIX owl: <http://www.w3.org/2002/07/owl#>\nSELECT DISTINCT ?directiveCelex ?directiveWork ?nim ?nimCelex ?relation ?direction WHERE {{\n VALUES ?directiveCelex {{ {vals} }}\n ?directiveWork owl:sameAs ?directiveCelex .\n {{ ?nim ?relation ?directiveWork . BIND("NIM_TO_DIRECTIVE" AS ?direction) }}\n UNION\n {{ ?directiveWork ?relation ?nim . BIND("DIRECTIVE_TO_NIM" AS ?direction) }}\n ?nim owl:sameAs ?nimCelex .\n FILTER(STRSTARTS(STR(?nimCelex), "{CELEX_URI}7"))\n FILTER(CONTAINS(UCASE(STR(?nimCelex)), "FRA_"))\n FILTER(?nim != ?directiveWork)\n}} ORDER BY ?directiveCelex ?nimCelex ?relation'''

def post(query,endpoint=ENDPOINT,timeout=90):
    data=urllib.parse.urlencode({'query':query}).encode()
    req=urllib.request.Request(endpoint,data=data,headers={'Accept':'application/sparql-results+json','Content-Type':'application/x-www-form-urlencoded','User-Agent':'legal-simplification-r7.2.1/1.0'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)

def parse_binding(b):
    def v(k): return b.get(k,{}).get('value')
    dc=(v('directiveCelex') or '').rsplit('/',1)[-1]
    nc=urllib.parse.unquote((v('nimCelex') or '').rsplit('/',1)[-1]).upper()
    m=NIM_RE.match(nc); sm=STAR_RE.match(nc)
    return {'schema_version':SCHEMA,'eu_celex':dc.upper(),'eu_work_uri':v('directiveWork'),'nim_work_uri':v('nim'),
      'nim_celex':nc,'country':'FRA','relation_predicate':v('relation'),'relation_direction':v('direction'),
      'nim_celex_shape':'STANDARD' if m else ('MULTI_ACT_STAR' if sm else 'OTHER'),
      'nim_database_id':int((m or sm).group('id')) if (m or sm) else None,
      'discovery_method':'CELLAR_RDF_RELATION'}

def discover(identity,out_dir,batch_size=50,endpoint=ENDPOINT,retries=4,sleep=1.0,limit=None):
    celex=directive_celexes(identity)
    if limit: celex=celex[:limit]
    od=Path(out_dir); cache=od/'cache'; cache.mkdir(parents=True,exist_ok=True)
    raw=[]; failed=[]
    for i in range(0,len(celex),batch_size):
        batch=celex[i:i+batch_size]; q=sparql(batch); key=hashlib.sha256('\n'.join(batch).encode()).hexdigest()
        cp=cache/f'{key}.json'
        if cp.exists(): data=json.loads(cp.read_text(encoding='utf8'))
        else:
            err=None
            for a in range(retries):
                try: data=post(q,endpoint); cp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8'); break
                except Exception as e:
                    err=repr(e); time.sleep(sleep*(2**a))
            else:
                failed.append({'batch':batch,'error':err}); continue
        for b in data.get('results',{}).get('bindings',[]): raw.append(parse_binding(b))
    # exact dedupe; retain different observed RDF predicates/directions as provenance
    uniq={ (r['eu_celex'],r['nim_work_uri'],r['nim_celex'],r['relation_predicate'],r['relation_direction']):r for r in raw }
    edges=sorted(uniq.values(),key=lambda r:(r['eu_celex'],r['nim_celex'],r['relation_predicate'] or '',r['relation_direction'] or ''))
    # one logical EU->NIM pair with all predicates retained
    g=defaultdict(list)
    for r in edges:g[(r['eu_celex'],r['nim_work_uri'],r['nim_celex'])].append(r)
    logical=[]
    for (eu,w,nc),rs in sorted(g.items()):
        logical.append({'schema_version':SCHEMA,'eu_celex':eu,'nim_work_uri':w,'nim_celex':nc,'country':'FRA',
          'nim_celex_shape':rs[0]['nim_celex_shape'],'nim_database_id':rs[0]['nim_database_id'],
          'relation_evidence':sorted({(x['relation_direction'],x['relation_predicate']) for x in rs}),
          'discovery_method':'CELLAR_RDF_RELATION'})
    ep=od/'r7_2_1_nim_france.jsonl'; rp=od/'r7_2_1_relation_evidence.jsonl'; fp=od/'r7_2_1_failed_batches.jsonl'
    ep.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in logical),encoding='utf8')
    rp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in edges),encoding='utf8')
    fp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in failed),encoding='utf8')
    covered={x['eu_celex'] for x in logical}; pred=Counter(x['relation_predicate'] for x in edges); dirs=Counter(x['relation_direction'] for x in edges); shapes=Counter(x['nim_celex_shape'] for x in logical)
    summary={'schema_version':SCHEMA,'directives_queried':len(celex),'directives_with_french_nim':len(covered),'directives_without_french_nim':len(celex)-len(covered),
      'logical_eu_nim_links':len(logical),'distinct_nim_works':len({x['nim_work_uri'] for x in logical}),
      'nim_celex_shapes':dict(shapes),'relation_predicates':dict(pred),'relation_directions':dict(dirs),'failed_batches':len(failed),
      'invariants':{'logical_links_unique':len(logical)==len({(x['eu_celex'],x['nim_work_uri'],x['nim_celex']) for x in logical}),
                    'country_is_france':all(x['country']=='FRA' for x in logical)},
      'outputs':{'nim_france':str(ep),'relation_evidence':str(rp),'failed_batches':str(fp),'cache':str(cache)}}
    (od/'r7_2_1_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); return summary
