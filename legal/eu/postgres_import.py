from __future__ import annotations
import json
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "001_eu_corpus.sql"

def rows(path):
    with Path(path).open(encoding="utf8") as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def first(row, *keys):
    for key in keys:
        value=row.get(key)
        if value not in (None, ""): return value
    return None

def date10(value):
    s=str(value or "")[:10]
    return s if len(s)==10 else None

def canonical_act(row):
    return {"celex":str(first(row,"legal_act_celex","celex","canonical_celex") or ""),
            "cellar_uuid":first(row,"cellar_uuid","canonical_cellar_uuid"),"eli":first(row,"eli"),
            "act_type":first(row,"act_type","type"),"title":first(row,"title","titre","work_title"),
            "document_date":date10(first(row,"document_date","date_document","date")),
            "legal_status":first(row,"legal_status","status"),"metadata":row}

def canonical_provision(row):
    return {"provision_id":str(first(row,"provision_id","id") or ""),
            "celex":str(first(row,"legal_act_celex","celex","canonical_celex") or ""),
            "cellar_uuid":first(row,"cellar_uuid"),"parent_id":first(row,"parent_id"),
            "kind":str(first(row,"kind") or ""),"label":first(row,"label","article_label","number","numero"),
            "logical_path":first(row,"logical_path","path","provision_path"),
            "text":str(first(row,"visible_text","text","texte","content","contenu","text_subtree") or ""),"metadata":row}

def classify_provision(p):
    missing=[]
    if not p["provision_id"]: missing.append("MISSING_PROVISION_ID")
    if not p["celex"]: missing.append("MISSING_CELEX")
    if not p["kind"]: missing.append("MISSING_KIND")
    return missing

def prepare(identity_path, provisions_path):
    acts={}; bad_acts=[]
    for raw in rows(identity_path):
        act=canonical_act(raw)
        if act["celex"]: acts[act["celex"]]=act
        else: bad_acts.append(raw)
    provisions=[]; bad_provisions=[]; empty_text=0; synthetic=set()
    for raw in rows(provisions_path):
        p=canonical_provision(raw); missing=classify_provision(p)
        if missing: bad_provisions.append({"reasons":missing,"row":raw}); continue
        empty_text += not bool(p["text"])
        if p["celex"] not in acts:
            synthetic.add(p["celex"]); acts[p["celex"]]={"celex":p["celex"],"cellar_uuid":None,"eli":None,"act_type":None,"title":None,"document_date":None,"legal_status":"SYNTHETIC_PARENT_FROM_PROVISION","metadata":{"synthetic_parent":True,"reason":"PROVISION_CELEX_ABSENT_FROM_IDENTITY"}}
        provisions.append(p)
    return acts,provisions,bad_acts,bad_provisions,empty_text,synthetic

ACT_SQL="""INSERT INTO eu_act(celex,cellar_uuid,eli,act_type,title,document_date,legal_status,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(celex) DO UPDATE SET cellar_uuid=excluded.cellar_uuid,eli=excluded.eli,act_type=excluded.act_type,title=excluded.title,document_date=excluded.document_date,legal_status=excluded.legal_status,metadata=excluded.metadata"""
PROV_SQL="""INSERT INTO eu_provision(provision_id,celex,cellar_uuid,parent_id,kind,label,logical_path,text,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(provision_id) DO UPDATE SET celex=excluded.celex,cellar_uuid=excluded.cellar_uuid,parent_id=excluded.parent_id,kind=excluded.kind,label=excluded.label,logical_path=excluded.logical_path,text=excluded.text,metadata=excluded.metadata"""

def import_corpus(conn, identity_path, provisions_path, batch_size=2000, audit_dir="artifacts/eu/import"):
    with conn.cursor() as cur: cur.execute(MIGRATION.read_text(encoding="utf8"))
    conn.commit()
    acts,provisions,bad_acts,bad_provisions,empty_text,synthetic=prepare(identity_path,provisions_path)
    out=Path(audit_dir); out.mkdir(parents=True,exist_ok=True)
    for name,data in (("invalid_acts.jsonl",bad_acts),("invalid_provisions.jsonl",bad_provisions),("synthetic_parents.jsonl",[acts[x] for x in sorted(synthetic)])):
        (out/name).write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in data),encoding="utf8")
    with conn.cursor() as cur:
        batch=[]
        for a in acts.values():
            batch.append((a["celex"],a["cellar_uuid"],a["eli"],a["act_type"],a["title"],a["document_date"],a["legal_status"],json.dumps(a["metadata"],ensure_ascii=False)))
            if len(batch)>=batch_size: cur.executemany(ACT_SQL,batch); batch=[]
        if batch: cur.executemany(ACT_SQL,batch)
        batch=[]
        for p in provisions:
            batch.append((p["provision_id"],p["celex"],p["cellar_uuid"],p["parent_id"],p["kind"],p["label"],p["logical_path"],p["text"],json.dumps(p["metadata"],ensure_ascii=False)))
            if len(batch)>=batch_size: cur.executemany(PROV_SQL,batch); batch=[]
        if batch: cur.executemany(PROV_SQL,batch)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM eu_act"); db_acts=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM eu_provision"); db_provisions=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM eu_provision WHERE text='' "); db_empty=cur.fetchone()[0]
    summary={"schema_version":"eu-postgres-v1","identity_rows_valid":len(acts)-len(synthetic),"invalid_acts":len(bad_acts),"synthetic_parents":len(synthetic),"input_provisions_preserved":len(provisions),"invalid_provisions":len(bad_provisions),"empty_text_provisions":empty_text,"db_acts":db_acts,"db_provisions":db_provisions,"db_empty_text_provisions":db_empty,"invariants":{"empty_text_is_not_invalid":True,"no_valid_provision_dropped":len(bad_provisions)==0,"provision_count_preserved":db_provisions>=len(provisions),"idempotent_upsert":True}}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return summary
