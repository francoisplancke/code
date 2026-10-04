import json
from legal.eu.nim_france import directive_celexes,parse_binding,sparql

def test_directive_selection(tmp_path):
 p=tmp_path/'i';p.write_text('\n'.join(json.dumps(x) for x in [
  {'status':'RESOLVED','act_type':'DIRECTIVE','celex':'32024L1500'},
  {'status':'RESOLVED','act_type':'DIRECTIVE','celex':'32024L1500R(01)'},
  {'status':'RESOLVED','act_type':'REGULATION','celex':'32024R1500'}])+'\n')
 assert directive_celexes(p)==['32024L1500']
def test_parse_standard():
 b={'directiveCelex':{'value':'http://publications.europa.eu/resource/celex/32014L0040'},'directiveWork':{'value':'w1'},'nim':{'value':'w2'},'nimCelex':{'value':'http://publications.europa.eu/resource/celex/72014L0040FRA_240395'},'relation':{'value':'http://x/p'},'direction':{'value':'NIM_TO_DIRECTIVE'}}
 r=parse_binding(b);assert r['nim_celex_shape']=='STANDARD' and r['nim_database_id']==240395 and r['country']=='FRA'
def test_parse_star():
 b={'directiveCelex':{'value':'http://publications.europa.eu/resource/celex/32024L1500'},'directiveWork':{'value':'w1'},'nim':{'value':'w2'},'nimCelex':{'value':'http://publications.europa.eu/resource/celex/7%2AFRA_202607159'},'relation':{'value':'http://x/p'},'direction':{'value':'NIM_TO_DIRECTIVE'}}
 assert parse_binding(b)['nim_celex_shape']=='MULTI_ACT_STAR'
def test_query_is_schema_discovery():
 q=sparql(['32024L1500']);assert '?nim ?relation ?directiveWork' in q and '?directiveWork ?relation ?nim' in q and 'FRA_' in q
