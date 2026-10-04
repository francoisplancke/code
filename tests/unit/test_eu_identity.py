from legal.eu.identity_reconcile_v11 import *
def o(s="UNRESOLVED",c=None):return {"status":s,"celex":c}
def s(st="RESOLVED",c="32000L0060",aliases=None):return {"status":st,"celex":c,"same_as":aliases or []}
def test_confirm():assert reconcile("u",o("RESOLVED","32000L0060"),s())["comparison"]=="SPARQL_CONFIRMS_FMX"
def test_conflict():assert reconcile("u",o("RESOLVED","32001L0001"),s())["comparison"]=="SPARQL_CONTRADICTS_FMX"
def test_v21_outscope():
 r=reconcile("u",o(),s("NO_SECTOR3_CELEX",None,["http://publications.europa.eu/resource/celex/C2017%2F168%2F02"]))
 assert r["status"]=="OUT_OF_SCOPE_CELEX" and r["comparison"]=="NO_SECTOR3_CELEX" and r["sparql_celex_aliases_all"]==["C2017/168/02"]
def test_legacy_nocelex_outscope():assert reconcile("u",o(),s("NO_CELEX",None))["status"]=="OUT_OF_SCOPE_CELEX"
def test_real_error_distinct():assert reconcile("u",o(),s("SPARQL_ERROR",None))["comparison"]=="SPARQL_ERROR_UNRESOLVED"
def test_directive_suffix():assert parse("32014L0001(01)")["act_type"]=="DIRECTIVE"
def test_corrigendum():assert parse("32025R1178R(02)")["act_type"]=="REGULATION"
