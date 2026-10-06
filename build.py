#!/usr/bin/env python3
"""Reproducible build entry point for the French LEGI and EU corpora."""
from __future__ import annotations
import os
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ART=ROOT/"artifacts"/"eu"
DEFAULT_DSN=os.getenv("LEGAL_DSN")
DEFAULT_EMBEDDING_MODEL=os.getenv("LEGAL_EMBEDDING_MODEL") or os.getenv("LEGAL_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def show(name, value):
    print(f"\n== {name} ==\n"+json.dumps(value,ensure_ascii=False,indent=2))

def build_legi(source, dsn, model, device, no_vectorize=False):
    cmd=[sys.executable,str(ROOT/"parse_legi_postgres.py"),str(source),"--dsn",dsn,"--embedding-model",model]
    if device: cmd += ["--embedding-device",device]
    if no_vectorize: cmd.append("--no-vectorize")
    subprocess.run(cmd,check=True,cwd=ROOT)

def vectorize_legi(dsn, model, device, batch_size=64, fetch_size=1000, create_hnsw=True):
    from parse_legi_postgres import vectorize_vigueur
    return vectorize_vigueur(dsn=dsn, model_name=model, batch_size=batch_size, fetch_size=fetch_size, device=device, create_hnsw=create_hnsw)

def build_eu(zip_path, dsn, batch=250):
    import psycopg
    from legal.eu.fmx_inventory import inventory
    from legal.eu.legal_identity import resolve_jsonl
    from legal.eu.cellar_sparql import run as cellar_run
    from legal.eu.cellar_sparql_v21 import reclassify
    from legal.eu.identity_reconcile_v11 import run as reconcile
    from legal.eu.provision_tree import run as provisions
    from legal.eu.legal_normalize import run as normalize
    from legal.eu.postgres_import import import_corpus
    ART.mkdir(parents=True,exist_ok=True)
    inv=ART/"inventory.jsonl"; invsum=ART/"inventory.summary.json"
    show("EU 1/7 inventory FMX",inventory(zip_path,inv,invsum))
    offline=ART/"identity.offline.jsonl"; offsum=ART/"identity.offline.summary.json"
    show("EU 2/7 offline identity",resolve_jsonl(inv,offline,offsum))
    raw=ART/"identity.cellar.raw.jsonl"
    show("EU 3/7 CELLAR identity",cellar_run(str(inv)+".cellar.jsonl",raw,ART/"cache"/"cellar",batch,None))
    fixed=ART/"identity.cellar.jsonl"
    show("EU 4/7 CELEX normalization",reclassify(raw,fixed,ART/"identity.cellar.summary.json"))
    identity=ART/"identity.jsonl"
    show("EU 5/7 canonical identity",reconcile(offline,fixed,identity,ART/"identity.summary.json",ART/"identity.conflicts.jsonl",ART/"identity.out_of_scope.jsonl",ART/"identity.duplicates.jsonl"))
    pdir=ART/"provisions"
    show("EU 6/7 provision tree",provisions(zip_path,identity,inv,pdir,None))
    ndir=ART/"normalized"
    show("EU normalization",normalize(identity,pdir/"r7_1_2_provisions.jsonl",ndir))
    with psycopg.connect(dsn) as conn:
        result=import_corpus(conn,ndir/"r7_2_0_documents.jsonl",ndir/"r7_2_0_provisions_normalized.jsonl",audit_dir=ART/"import")
    show("EU 7/7 PostgreSQL import",result)
    if not result["invariants"]["no_valid_provision_dropped"] or not result["invariants"]["provision_count_preserved"]:
        raise SystemExit("EU import invariants failed; inspect artifacts/eu/import")

def build_nim(batch=50):
    from legal.eu.nim_france import discover
    from legal.eu.nim_metadata import run, ENDPOINT
    identity=ART/"identity.jsonl"
    if not identity.exists(): raise SystemExit("Run `python build.py eu ...` first")
    out1=ART/"nim"/"discovery"; out2=ART/"nim"/"metadata"
    show("NIM discovery",discover(identity,out1,batch,ENDPOINT))
    show("NIM metadata",run(out1/"r7_2_1_nim_france.jsonl",out2,batch,ENDPOINT))

def main():
    p=argparse.ArgumentParser(description="Build the legal PostgreSQL database")
    sub=p.add_subparsers(dest="cmd",required=True)
    l=sub.add_parser("legi",help="import/vectorize the French LEGI corpus")
    l.add_argument("source",nargs="?",default=os.getenv("LEGAL_LEGI_ARCHIVE")); l.add_argument("--dsn",default=DEFAULT_DSN)
    l.add_argument("--model",default=DEFAULT_EMBEDDING_MODEL); l.add_argument("--device",default=os.getenv("LEGAL_DEVICE")); l.add_argument("--no-vectorize",action="store_true")
    v=sub.add_parser("vectorize",help="vectorize already imported LEGI versions without reimport")
    v.add_argument("--dsn",default=DEFAULT_DSN); v.add_argument("--model",default=DEFAULT_EMBEDDING_MODEL); v.add_argument("--device",default=os.getenv("LEGAL_EMBEDDING_DEVICE") or os.getenv("LEGAL_DEVICE"))
    v.add_argument("--batch-size",type=int,default=64); v.add_argument("--fetch-size",type=int,default=1000); v.add_argument("--no-hnsw",action="store_true")
    e=sub.add_parser("eu",help="build EU corpus from the official FMX dump and import PostgreSQL")
    e.add_argument("source",nargs="?",default=os.getenv("LEGAL_EU_FMX_ZIP")); e.add_argument("--dsn",default=DEFAULT_DSN); e.add_argument("--sparql-batch",type=int,default=250)
    n=sub.add_parser("nim",help="optional: discover/enrich French national transposition measures")
    n.add_argument("--batch",type=int,default=50)
    a=sub.add_parser("all",help="build LEGI then EU")
    a.add_argument("--legi",default=os.getenv("LEGAL_LEGI_ARCHIVE")); a.add_argument("--eu",default=os.getenv("LEGAL_EU_FMX_ZIP")); a.add_argument("--dsn",default=DEFAULT_DSN)
    a.add_argument("--model",default=DEFAULT_EMBEDDING_MODEL); a.add_argument("--device",default=os.getenv("LEGAL_DEVICE"))
    x=p.parse_args()
    if x.cmd=="legi":
        if not x.source: p.error("LEGI source required (argument or LEGAL_LEGI_ARCHIVE)")
        build_legi(x.source,x.dsn,x.model,x.device,x.no_vectorize)
    elif x.cmd=="vectorize":
        if not x.dsn: p.error("LEGAL_DSN/--dsn required")
        show("LEGI vectorization", vectorize_legi(x.dsn,x.model,x.device,x.batch_size,x.fetch_size,not x.no_hnsw))
    elif x.cmd=="eu":
        if not x.source: p.error("EU FMX ZIP required (argument or LEGAL_EU_FMX_ZIP)")
        build_eu(x.source,x.dsn,x.sparql_batch)
    elif x.cmd=="nim": build_nim(x.batch)
    else:
        if not x.legi or not x.eu: p.error("--legi/LEGAL_LEGI_ARCHIVE and --eu/LEGAL_EU_FMX_ZIP are required")
        build_legi(x.legi,x.dsn,x.model,x.device); build_eu(x.eu,x.dsn)
if __name__=="__main__": main()
