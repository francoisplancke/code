"""On-demand evidence verification with PostgreSQL-backed cache (R7.4.2.1).

VERIFIED means textual integrity only, never legal correctness. Caller commits.
"""
from __future__ import annotations
import hashlib
import json
from uuid import UUID

VALIDATOR_VERSION = "r7.4.2.1-evidence-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_evidence(*, source_text: str | None, source_checksum: str,
                    source_excerpt: str, span_start: int | None,
                    span_end: int | None) -> tuple[str, list[str]]:
    if source_text is None:
        return "SOURCE_MISSING", ["SOURCE_NOT_FOUND"]
    issues = []
    if _sha(source_text) != source_checksum:
        issues.append("SOURCE_CHECKSUM_MISMATCH")
    if not isinstance(source_excerpt, str) or not source_excerpt.strip():
        issues.append("EMPTY_EXCERPT")
    if type(span_start) is not int or type(span_end) is not int or not 0 <= span_start < span_end <= len(source_text):
        issues.append("INVALID_SPAN")
    elif source_text[span_start:span_end] != source_excerpt:
        issues.append("EXCERPT_MISMATCH")
    return ("INVALID" if issues else "VERIFIED"), issues


def ensure_evidence_checked(conn, obligation_id, *, force=False):
    """Verify a stored EU or FR obligation once per source+evidence+validator version.

    Locks obligation row to serialize concurrent checks. Recomputes current source
    checksum before consulting cache; a changed source invalidates the cache.
    Caller controls transaction and commit; no external LLM calls.
    """
    oid = UUID(str(obligation_id))
    row = conn.execute("""
        SELECT o.jurisdiction, o.eu_provision_id, o.legi_version_id,
               o.source_checksum, o.source_excerpt, o.span_start, o.span_end
          FROM legal_obligation o
         WHERE o.obligation_id = %s FOR UPDATE OF o
    """, (oid,)).fetchone()
    if row is None:
        raise LookupError(f"obligation not found: {oid}")
    jurisdiction, eu_id, fr_id, original_checksum, excerpt, start, end = row
    if jurisdiction == 'EU':
        source = conn.execute('SELECT text FROM eu_provision WHERE provision_id=%s', (eu_id,)).fetchone()
    elif jurisdiction == 'FR':
        source = conn.execute('SELECT contenu FROM version WHERE id=%s', (fr_id,)).fetchone()
    else:
        raise ValueError(f"unsupported jurisdiction: {jurisdiction}")
    source_text = source[0] if source is not None else None
    current_checksum = _sha(source_text) if source_text is not None else None
    fingerprint = _sha(json.dumps({
        'jurisdiction': jurisdiction, 'eu_id': eu_id, 'fr_id': str(fr_id) if fr_id else None,
        'source_checksum': original_checksum, 'excerpt': excerpt,
        'start': start, 'end': end,
    }, sort_keys=True, ensure_ascii=False))
    cached = conn.execute("""
        SELECT status, source_checksum, obligation_fingerprint, validator_version, issues, checked_at
          FROM legal_obligation_evidence_check WHERE obligation_id=%s
    """, (oid,)).fetchone()
    if (not force and cached is not None and cached[1] == current_checksum
            and cached[2] == fingerprint and cached[3] == VALIDATOR_VERSION):
        return {'obligation_id': str(oid), 'status': cached[0], 'issues': cached[4],
                'cached': True, 'validator_version': VALIDATOR_VERSION}
    status, issues = verify_evidence(source_text=source_text, source_checksum=original_checksum,
                                     source_excerpt=excerpt, span_start=start, span_end=end)
    conn.execute("""
        INSERT INTO legal_obligation_evidence_check
            (obligation_id,status,source_checksum,obligation_fingerprint,validator_version,issues,checked_at)
        VALUES (%s,%s,%s,%s,%s,%s::jsonb,now())
        ON CONFLICT (obligation_id) DO UPDATE SET
            status=EXCLUDED.status, source_checksum=EXCLUDED.source_checksum,
            obligation_fingerprint=EXCLUDED.obligation_fingerprint,
            validator_version=EXCLUDED.validator_version, issues=EXCLUDED.issues,
            checked_at=now()
    """, (oid, status, current_checksum, fingerprint, VALIDATOR_VERSION, json.dumps(issues)))
    return {'obligation_id': str(oid), 'status': status, 'issues': issues,
            'cached': False, 'validator_version': VALIDATOR_VERSION}
