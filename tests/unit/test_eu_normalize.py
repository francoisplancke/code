import json
from legal.eu.legal_normalize import parse_corrigendum,run
def w(p,x):p.write_text(''.join(json.dumps(i)+'\n' for i in x))
def test_parse():
 assert parse_corrigendum('32013L0053R(01)')=={'base_celex':'32013L0053','corrigendum_number':1}
 assert parse_corrigendum('32012A0424(01)R(02)')=={'base_celex':'32012A0424(01)','corrigendum_number':2}
 assert parse_corrigendum('32013L0053') is None
def test_present(tmp_path):
 i=tmp_path/'i';p=tmp_path/'p';o=tmp_path/'o';w(i,[{'cellar_uuid':'b','celex':'32013L0053','status':'RESOLVED','act_type':'DIRECTIVE'},{'cellar_uuid':'c','celex':'32013L0053R(01)','status':'RESOLVED','act_type':'DIRECTIVE'}]);w(p,[{'provision_id':'x','cellar_uuid':'c','celex':'32013L0053R(01)','kind':'ARTICLE'}]);s=run(i,p,o);assert s['missing_base_targets']==0;q=json.loads((o/'r7_2_0_provisions_normalized.jsonl').read_text());assert q['legal_act_celex']=='32013L0053' and q['provision_id']=='x'
def test_missing(tmp_path):
 i=tmp_path/'i';p=tmp_path/'p';o=tmp_path/'o';w(i,[{'cellar_uuid':'c','celex':'32013L0053R(02)','status':'RESOLVED','act_type':'DIRECTIVE'}]);w(p,[]);s=run(i,p,o);assert s['missing_base_targets']==1
