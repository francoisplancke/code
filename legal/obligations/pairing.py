"""R7.4.3: conservative, evidence-gated EU↔FR candidate matching.

Scope is EXPLICIT: caller must supply verified French LEGI version IDs.
No implicit CELEX->FR mapping is inferred from NIM metadata.
"""
from __future__ import annotations
import json
import re
import uuid
import unicodedata
from .evidence import ensure_evidence_checked

ALGORITHM_VERSION = 'r7.4.3-lexical-v1'
_STOP = frozenset('de du des le la les un une et ou a au aux en dans pour par sur est sont être etre que qui se son sa ses ce cette ces doit doivent peut peuvent faire objet'.split())

def tokens(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(c for c in value if not unicodedata.combining(c)).lower()
    return {w for w in re.findall(r'[a-z0-9]{3,}', value) if w not in _STOP}

def score_pair(eu, fr):
    """Return a transparent ranking signal, NOT legal equivalence."""
    fields = ('action', 'object', 'actor')
    weights = {'action': .50, 'object': .35, 'actor': .15}
    parts = {}
    applicable = 0.0
    weighted = 0.0
    for field in fields:
        left, right = tokens(eu.get(field)), tokens(fr.get(field))
        if not left or not right:
            parts[field] = None
            continue
        similarity = len(left & right) / len(left | right)
        parts[field] = round(similarity, 4)
        weighted += weights[field] * similarity
        applicable += weights[field]
    lexical = weighted / applicable if applicable else 0.0
    same_modality = eu.get('modality') == fr.get('modality')
    score = round(lexical * (1.0 if same_modality else .75), 4)
    return score, {'field_jaccard': parts, 'same_modality': same_modality,
                   'eu_conditions': eu.get('conditions') or [], 'fr_conditions': fr.get('conditions') or [],
                   'eu_exceptions': eu.get('exceptions') or [], 'fr_exceptions': fr.get('exceptions') or [],
                   'warning': 'Ranking signal only; compare legal scope, thresholds, exceptions and EU discretion manually.'}

def _latest_obligations(conn, jurisdiction, source_column, source_ids):
    if not source_ids:
        return []
    # Latest successful extraction per source, not union of historical model runs.
    sql = f"""SELECT o.obligation_id, o.actor, o.modality, o.action, o.object,
                     o.conditions, o.exceptions, o.{source_column}
              FROM legal_obligation o JOIN legal_obligation_run r ON r.run_id=o.run_id
              WHERE o.jurisdiction=%s AND o.{source_column}=ANY(%s)
                AND r.status='SUCCEEDED' AND o.review_status <> 'REJECTED'
                AND o.run_id = (
                    SELECT o2.run_id FROM legal_obligation o2
                    JOIN legal_obligation_run r2 ON r2.run_id=o2.run_id
                    WHERE o2.jurisdiction=o.jurisdiction AND o2.{source_column}=o.{source_column}
                      AND r2.status='SUCCEEDED'
                    ORDER BY r2.started_at DESC, r2.run_id DESC LIMIT 1
                )"""
    rows = conn.execute(sql, (jurisdiction, source_ids)).fetchall()
    return [dict(zip(('obligation_id','actor','modality','action','object','conditions','exceptions','source_id'), r)) for r in rows]

def pair_scope(conn, *, eu_celex, fr_version_ids, scope_reference,
               scope_origin='MANUAL_VERIFIED', minimum_score=.15, limit=1000):
    """Persist candidates for an explicitly established EU/FR scope.

    Caller owns transaction. Evidence checks write to the same transaction.
    Missing/invalid evidence is never paired. No LLM/network calls.
    """
    if scope_origin not in ('MANUAL_VERIFIED', 'NIM_RESOLVED'):
        raise ValueError('invalid scope_origin')
    if not eu_celex or not scope_reference or not fr_version_ids:
        raise ValueError('eu_celex, scope_reference and fr_version_ids are required')
    if not 0 <= minimum_score <= 1 or limit < 1:
        raise ValueError('invalid minimum_score or limit')
    fr_ids = [uuid.UUID(str(x)) for x in dict.fromkeys(map(str, fr_version_ids))]
    # Confirm actual source identities; no guessed NIM->LEGI relationship.
    act = conn.execute('SELECT 1 FROM eu_act WHERE celex=%s', (eu_celex,)).fetchone()
    if not act:
        raise LookupError('EU act not found')
    known = {r[0] for r in conn.execute('SELECT id FROM version WHERE id=ANY(%s)', (fr_ids,)).fetchall()}
    if len(known) != len(fr_ids):
        raise LookupError('one or more FR version IDs not found')
    eu_ids = [r[0] for r in conn.execute('SELECT provision_id FROM eu_provision WHERE celex=%s', (eu_celex,)).fetchall()]
    eu = _latest_obligations(conn, 'EU', 'eu_provision_id', eu_ids)
    fr = _latest_obligations(conn, 'FR', 'legi_version_id', fr_ids)
    verified = {'EU': [], 'FR': []}
    skipped = {'EU': [], 'FR': []}
    for jurisdiction, items in (('EU', eu), ('FR', fr)):
        for item in items:
            check = ensure_evidence_checked(conn, item['obligation_id'])
            if check['status'] == 'VERIFIED':
                verified[jurisdiction].append(item)
            else:
                skipped[jurisdiction].append({'obligation_id':str(item['obligation_id']), 'status':check['status']})
    candidates = []
    for e in verified['EU']:
        for f in verified['FR']:
            score, features = score_pair(e, f)
            if score >= minimum_score:
                candidates.append((score, e, f, features))
    candidates.sort(key=lambda x: (-x[0], str(x[1]['obligation_id']), str(x[2]['obligation_id'])))
    candidates = candidates[:limit]
    for score, e, f, features in candidates:
        conn.execute("""INSERT INTO legal_obligation_pair
            (pair_id,eu_obligation_id,fr_obligation_id,eu_celex,scope_origin,
             scope_reference,algorithm_version,similarity,decision,features)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'REVIEW_REQUIRED',%s::jsonb)
            ON CONFLICT (eu_obligation_id,fr_obligation_id,algorithm_version,scope_origin,scope_reference)
            DO UPDATE SET similarity=EXCLUDED.similarity,features=EXCLUDED.features,updated_at=now()""",
            (uuid.uuid4(),e['obligation_id'],f['obligation_id'],eu_celex,scope_origin,
             scope_reference,ALGORITHM_VERSION,score,json.dumps(features,ensure_ascii=False)))
    return {'eu_celex':eu_celex, 'eu_verified':len(verified['EU']),
            'fr_verified':len(verified['FR']), 'skipped':skipped,
            'candidates_persisted':len(candidates), 'truncated':len(candidates)==limit,
            'algorithm_version':ALGORITHM_VERSION}
