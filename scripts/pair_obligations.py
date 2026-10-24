#!/usr/bin/env python3
"""Explicit scope only. Requires a trusted CELEX + LEGI version mapping."""
import argparse
import json
import os
import psycopg
from legal.obligations.pairing import pair_scope

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--celex', required=True)
    parser.add_argument('--fr-version-id', action='append', required=True)
    parser.add_argument('--scope-reference', required=True, help='Provenance of verified mapping')
    parser.add_argument('--scope-origin', choices=['MANUAL_VERIFIED','NIM_RESOLVED'], default='MANUAL_VERIFIED')
    parser.add_argument('--min-score', type=float, default=.15)
    args=parser.parse_args()
    dsn=os.getenv('LEGAL_DSN') or os.getenv('DATABASE_DSN')
    if not dsn:
        parser.error('LEGAL_DSN or DATABASE_DSN required')
    with psycopg.connect(dsn) as conn:
        result=pair_scope(conn, eu_celex=args.celex, fr_version_ids=args.fr_version_id,
                          scope_reference=args.scope_reference,scope_origin=args.scope_origin,
                          minimum_score=args.min_score)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
