#!/usr/bin/env python3
"""Sequential R7.4.3.1 EU/FR sample processor; resume is idempotent."""
import argparse
import json
import os
import sys
import psycopg
from legal.obligations.cascade import process_source, CreditExhausted, POLICY_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jurisdiction', choices=('EU','FR'), required=True)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--source-id', action='append', help='Explicit provision_id or version.id; repeatable')
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be 1..1000')
    dsn = os.getenv('DATABASE_DSN') or os.getenv('LEGAL_DSN')
    if not dsn:
        parser.error('DATABASE_DSN or LEGAL_DSN required')
    table, id_col, text_col = (('eu_provision','provision_id','text') if args.jurisdiction == 'EU'
                               else ('version','id','contenu'))
    with psycopg.connect(dsn) as conn:
        if args.source_id:
            rows = conn.execute(f'''SELECT {id_col}::text,{text_col} FROM {table}
                WHERE {id_col}::text = ANY(%s) AND {text_col} IS NOT NULL
                  AND length({text_col}) BETWEEN 1 AND 12000 LIMIT %s''',
                (args.source_id,args.limit)).fetchall()
        else:
            # Fetch only unprocessed sources; do not process all 1.3M LEGI articles by default.
            rows = conn.execute(f'''SELECT s.{id_col}::text,s.{text_col} FROM {table} s
                WHERE s.{text_col} IS NOT NULL AND length(s.{text_col}) BETWEEN 100 AND 12000
                AND NOT EXISTS (SELECT 1 FROM legal_extraction_cascade c
                  WHERE c.jurisdiction=%s AND c.source_id=s.{id_col}::text
                    AND c.source_checksum=encode(sha256(convert_to(s.{text_col},'UTF8')),'hex')
                    AND c.policy_version=%s)
                ORDER BY s.{id_col} LIMIT %s''', (args.jurisdiction,POLICY_VERSION,args.limit)).fetchall()
        conn.commit()
        for source_id, source_text in rows:
            try:
                result = process_source(conn, jurisdiction=args.jurisdiction,
                    source_id=source_id, source_text=source_text,
                    retry_failed=args.retry_failed)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except CreditExhausted as exc:
                print(str(exc), file=sys.stderr, flush=True)
                return 42
            except Exception as exc:
                print(f'ERREUR {source_id}: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
