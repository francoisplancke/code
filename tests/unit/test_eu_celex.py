from legal.eu.celex import *
from legal.eu.cellar_sparql_v21 import classify
B="http://publications.europa.eu/resource/celex/"
def test_percent_corrigendum():
 p=parse_sector3("32025R1178R%2802%29");assert p["celex"]=="32025R1178R(02)" and p["is_corrigendum"]
def test_old_sequence():
 p=parse_sector3("32014D0717%2801%29");assert p["sequence"]=="(01)" and not p["is_corrigendum"]
def test_q_sequence():
 assert parse_sector3("32011Q0712%2801%29")["descriptor"]=="Q"
def test_corrigendum():
 assert parse_sector3("32017R0391R%2801%29")["corrigendum"]=="R(01)"
def test_alias_decode_and_classify():
 r=classify("u",[B+"32025D01689R%2801%29"]);assert r["status"]=="RESOLVED" and r["celex"]=="32025D01689R(01)"
def test_non_sector3_stays_out():
 r=classify("u",[B+"52010XG0729%2801%29R%2801%29",B+"C2017%2F168%2F02"])
 assert r["status"]=="NO_SECTOR3_CELEX" and len(r["celex_aliases_decoded"])==2
def test_plain():
 assert parse_sector3("32000L0060")["descriptor"]=="L"
