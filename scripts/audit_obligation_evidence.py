#!/usr/bin/env python3
"""Audit des citations et positions des obligations EU/FR."""

import argparse
import json
import os
import sys

import psycopg


SQL = """
SELECT
    o.obligation_id::text,
    o.jurisdiction,
    o.eu_provision_id,
    o.legi_version_id::text,
    o.source_excerpt,
    o.span_start,
    o.span_end,
    o.source_checksum,
    p.text AS source_text
FROM legal_obligation o
LEFT JOIN eu_provision p
    ON o.jurisdiction = 'EU'
   AND p.provision_id = o.eu_provision_id
WHERE (%s::uuid IS NULL OR o.run_id = %s::uuid)
ORDER BY o.created_at, o.obligation_id
"""


def audit_row(row):
    (
        obligation_id,
        jurisdiction,
        eu_id,
        fr_id,
        excerpt,
        start,
        end,
        checksum,
        source_text,
    ) = row

    issues = []

    if jurisdiction == "FR":
        issues.append("FR_SOURCE_NOT_CONFIGURED")
    elif source_text is None:
        issues.append("SOURCE_NOT_FOUND")
    else:
        import hashlib

        actual_checksum = hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()

        if actual_checksum != checksum:
            issues.append("SOURCE_CHECKSUM_MISMATCH")

        if (
            type(start) is not int
            or type(end) is not int
            or not (0 <= start < end <= len(source_text))
        ):
            issues.append("INVALID_SPAN")
        elif source_text[start:end] != excerpt:
            issues.append("EXCERPT_MISMATCH")

    return {
        "obligation_id": obligation_id,
        "jurisdiction": jurisdiction,
        "source_id": eu_id if jurisdiction == "EU" else fr_id,
        "issues": issues,
        "ok": not issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dsn = os.getenv("LEGAL_DSN") or os.getenv("DATABASE_DSN")
    if not dsn:
        print("LEGAL_DSN ou DATABASE_DSN absent", file=sys.stderr)
        return 2

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            SQL, (args.run_id, args.run_id)
        ).fetchall()

    results = [audit_row(row) for row in rows]
    failures = [r for r in results if not r["ok"]]

    if args.json:
        print(json.dumps({
            "checked": len(results),
            "failed": len(failures),
            "failures": failures,
        }, ensure_ascii=False, indent=2))
    else:
        print(
            f"Obligations contrôlées : {len(results)} | "
            f"Anomalies : {len(failures)}"
        )
        for failure in failures:
            print(
                f"{failure['obligation_id']}: "
                f"{', '.join(failure['issues'])}"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())