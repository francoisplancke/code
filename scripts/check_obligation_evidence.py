#!/usr/bin/env python3
"""Check a single obligation on demand and persist result."""
import argparse
import json
import os
import sys
import psycopg
from legal.obligations.evidence import ensure_evidence_checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('obligation_id')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    dsn = os.getenv('LEGAL_DSN') or os.getenv('DATABASE_DSN')
    if not dsn:
        parser.error('LEGAL_DSN or DATABASE_DSN is required')
    with psycopg.connect(dsn) as conn:
        result = ensure_evidence_checked(conn, args.obligation_id, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'VERIFIED' else 1


if __name__ == '__main__':
    sys.exit(main())
