import json
from legal.eu.postgres_import import canonical_provision,classify_provision,prepare
def w(p,rs):
 with open(p,"w") as f:
  for r in rs:f.write(json.dumps(r)+"\n")
def test_empty_text_is_valid():
 p=canonical_provision({"provision_id":"p","legal_act_celex":"32020L0001","kind":"ARTICLE"})
 assert p["text"]=="" and classify_provision(p)==[]
def test_missing_identity_is_invalid():
 p=canonical_provision({"legal_act_celex":"32020L0001","kind":"ARTICLE"})
 assert classify_provision(p)==["MISSING_PROVISION_ID"]
def test_prepare_preserves_empty_and_creates_parent(tmp_path):
 i=tmp_path/"i";p=tmp_path/"p";w(i,[])
 w(p,[{"provision_id":"p","legal_act_celex":"32020L0001","kind":"ANNEX","visible_text":""}])
 acts,ps,ba,bp,empty,syn=prepare(i,p)
 assert len(ps)==1 and empty==1 and not bp and syn=={"32020L0001"}
 assert acts["32020L0001"]["legal_status"]=="SYNTHETIC_PARENT_FROM_PROVISION"
def test_real_identity_no_synthetic(tmp_path):
 i=tmp_path/"i";p=tmp_path/"p"
 w(i,[{"celex":"32020L0001","title":"x"}])
 w(p,[{"provision_id":"p","legal_act_celex":"32020L0001","kind":"ARTICLE","visible_text":"x"}])
 acts,ps,ba,bp,empty,syn=prepare(i,p)
 assert len(acts)==1 and len(ps)==1 and syn==set()
