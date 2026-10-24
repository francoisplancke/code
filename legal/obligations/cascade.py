"""R7.4.3.1: local -> DeepSeek reference -> Gemini arbitration.

Silver-label agreement only; never a legal correctness verdict.
"""
from __future__ import annotations
import json
import re
from urllib.error import HTTPError

from legal.llm.providers import _provider_config, chat
from legal.obligations.extract import checksum, llm_extract
from legal.obligations.storage import extract_and_store

POLICY_VERSION = 'r7.4.3.2-silver-v1'

class CreditExhausted(RuntimeError):
    pass


def is_credit_error(exc: BaseException) -> bool:
    """Conservative: only explicit billing/quota signals; 429 alone may be rate limit."""
    chain = []
    while exc is not None and len(chain) < 8:
        chain.append(exc)
        exc = exc.__cause__
    for e in chain:
        if isinstance(e, HTTPError):
            if e.code == 402:
                return True
            # Provider-specific 403/429 billing details, never include raw body in logs.
            try:
                body = e.read(4096).decode('utf-8', errors='replace').lower()
            except Exception:
                body = ''
            if e.code in (400, 403, 429) and re.search(
                r'insufficient[_ -]?(?:balance|quota|credit)|quota[_ -]?exceeded|'
                r'billing[_ -]?(?:hard[_ -]?limit|quota)|resource_exhausted|'
                r'credit[s]?[_ -]?exhausted|payment required', body):
                return True
    return False


def obligation_keys(items):
    """Strict semantic proxy, not legal equivalence; offsets are not compared."""
    keys = set()
    for item in items:
        o = item.obligation
        keys.add(tuple(str(o.get(k) or '').strip().casefold() for k in
                       ('modality', 'actor', 'action', 'object', 'deadline', 'frequency', 'threshold')))
    return keys


def compare(local, reference, *, local_valid=True, reference_valid=True):
    a, b = obligation_keys(local), obligation_keys(reference)
    if not local_valid or not reference_valid:
        return {'agreement': 'INVALID_COMPARISON', 'local_count': len(a),
                'reference_count': len(b), 'local_only': None, 'reference_only': None}
    return {'agreement': 'EXACT_FIELDS' if a == b else 'DISAGREEMENT',
            'local_count': len(a), 'reference_count': len(b),
            'local_only': len(a - b), 'reference_only': len(b - a)}


def _extract(text, provider):
    config = _provider_config(provider)
    def call(messages, *, temperature=0):
        return chat(messages, config=config, temperature=temperature)
    # Single network call: capture the exact request issued by llm_extract.
    cache = {}
    def recording_call(messages, *, temperature=0):
        if "response" not in cache:
            cache["response"] = call(messages, temperature=temperature)
        return cache["response"]
    items, _ = llm_extract(text, recording_call)
    return items, recording_call, config


def _claim(conn, jurisdiction, source_id, digest, *, retry_failed=False):
    key = (jurisdiction, source_id, digest, POLICY_VERSION)
    with conn.transaction():
        conn.execute('''INSERT INTO legal_extraction_cascade
            (jurisdiction,source_id,source_checksum,policy_version,status)
            VALUES (%s,%s,%s,%s,'FAILED') ON CONFLICT DO NOTHING''', key)
        row = conn.execute('''SELECT status,claimed_at FROM legal_extraction_cascade
            WHERE jurisdiction=%s AND source_id=%s AND source_checksum=%s AND policy_version=%s
            FOR UPDATE''', key).fetchone()
        if row[0] in ('COMPLETED', 'NEEDS_REVIEW'):
            return False
        if row[0] == 'RUNNING':
            # Manual intervention required for an interrupted worker: no silent replay.
            raise RuntimeError('source already RUNNING; inspect before retry')
        if row[0] in ('FAILED', 'CREDIT_EXHAUSTED') and not retry_failed:
            # Newly inserted row is FAILED with attempts=0.
            attempts = conn.execute('''SELECT attempts FROM legal_extraction_cascade
                WHERE jurisdiction=%s AND source_id=%s AND source_checksum=%s AND policy_version=%s''', key).fetchone()[0]
            if attempts:
                return False
        conn.execute('''UPDATE legal_extraction_cascade SET status='RUNNING',
            attempts=attempts+1, claimed_at=now(), last_error=NULL
            WHERE jurisdiction=%s AND source_id=%s AND source_checksum=%s AND policy_version=%s''', key)
    return True


def _update(conn, key, status, *, details=None, error=None):
    with conn.transaction():
        conn.execute('''UPDATE legal_extraction_cascade SET status=%s,
            completed_at=CASE WHEN %s IN ('COMPLETED','NEEDS_REVIEW') THEN now() ELSE NULL END,
            details=COALESCE(%s::jsonb,details),last_error=%s,
            agreement=COALESCE(%s,agreement)
            WHERE jurisdiction=%s AND source_id=%s AND source_checksum=%s AND policy_version=%s''',
            (status, status, json.dumps(details) if details is not None else None,
             error, details.get('agreement') if details else None, *key))


def process_source(conn, *, jurisdiction, source_id, source_text, retry_failed=False):
    if jurisdiction not in ('EU', 'FR'):
        raise ValueError('jurisdiction must be EU or FR')
    if not source_text or len(source_text) > 12000:
        raise ValueError('source must contain 1..12000 characters; segment long sources first')
    digest = checksum(source_text)
    key = (jurisdiction, str(source_id), digest, POLICY_VERSION)
    if not _claim(conn, *key[:3], retry_failed=retry_failed):
        return {'status':'SKIPPED', 'source_id':str(source_id)}
    details = {'models': {}, 'comparison': None}
    try:
        # The storage API currently performs its LLM call inside a DB transaction.
        # This worker is sequential; future version should separate inference and persistence.
        extracted = {}
        for provider in ('local', 'deepseek'):
            try:
                items, call, config = _extract(source_text, provider)
            except Exception as exc:
                if provider != 'local' or is_credit_error(exc):
                    raise
                # Local malformed output/unavailable: escalate rather than abort.
                extracted[provider] = []
                details['models'][provider] = {'uncertain': True, 'error': type(exc).__name__}
                continue
            extracted[provider] = items
            result = extract_and_store(conn, jurisdiction=jurisdiction, source_id=str(source_id),
                                       source_text=source_text, mode='llm', chat_fn=call,
                                       provider=provider, model=config.model)
            details['models'][provider] = {'run_id':result['run_id'], 'outcome':result['outcome'],
                                            'obligations':result['obligations']}
            if result['outcome'] in ('FAILED_VALIDATION','PARTIAL'):
                details['models'][provider]['uncertain'] = True
        valid = lambda provider: details['models'].get(provider, {}).get('outcome') in ('SUCCESS', 'EMPTY')
        comparison = compare(extracted['local'], extracted['deepseek'],
                             local_valid=valid('local'), reference_valid=valid('deepseek'))
        uncertain = any(x.get('uncertain') for x in details['models'].values())
        if comparison['agreement'] != 'EXACT_FIELDS' or uncertain:
            items, call, config = _extract(source_text, 'gemini')
            extracted['gemini'] = items
            result = extract_and_store(conn, jurisdiction=jurisdiction, source_id=str(source_id),
                                       source_text=source_text, mode='llm', chat_fn=call,
                                       provider='gemini', model=config.model)
            details['models']['gemini'] = {'run_id':result['run_id'], 'outcome':result['outcome'],
                                           'obligations':result['obligations']}
            comparison['gemini_vs_deepseek'] = compare(items, extracted['deepseek'],
                local_valid=valid('gemini'), reference_valid=valid('deepseek'))
            comparison['gemini_vs_local'] = compare(items, extracted['local'],
                local_valid=valid('gemini'), reference_valid=valid('local'))
            comparison['agreement'] = 'ARBITRATION_REQUIRED' if (
                comparison['gemini_vs_deepseek']['agreement'] != 'EXACT_FIELDS'
                or not valid('gemini')) else 'GEMINI_SUPPORTS_DEEPSEEK'
        details['comparison'] = comparison
        details['agreement'] = comparison['agreement']
        usable = (valid('deepseek') and
                  (comparison['agreement'] == 'EXACT_FIELDS' or
                   comparison['agreement'] == 'GEMINI_SUPPORTS_DEEPSEEK'))
        status = 'COMPLETED' if usable else 'NEEDS_REVIEW'
        details['reference_usable'] = usable
        _update(conn, key, status, details=details)
        return {'status':status, 'source_id':str(source_id), **details}
    except Exception as exc:
        if is_credit_error(exc):
            _update(conn, key, 'CREDIT_EXHAUSTED', details=details,
                    error='Provider billing/quota exhausted')
            raise CreditExhausted('ALERTE: crédit/quota DeepSeek ou Gemini épuisé; arrêt immédiat') from exc
        _update(conn, key, 'FAILED', details=details, error=f'{type(exc).__name__}: {str(exc)[:300]}')
        raise
