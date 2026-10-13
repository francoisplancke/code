"""Transactional PostgreSQL persistence of derived obligations."""
from __future__ import annotations
import json
import uuid
from .extract import checksum, PIPELINE_VERSION, PROMPT_VERSION, deterministic, llm_extract


def extract_and_store(conn, *, jurisdiction: str, source_id: str, source_text: str,
                      mode: str = 'deterministic', chat_fn=None, provider=None, model=None):
    """One run per source. Caller owns connection; errors roll back the whole run.

    Do not use this function inside a larger uncommitted transaction.
    """
    if jurisdiction not in ('FR', 'EU') or mode not in ('deterministic', 'llm', 'hybrid'):
        raise ValueError('invalid jurisdiction or extraction mode')
    if not source_text.strip() or not source_id:
        raise ValueError('source_id and source_text required')
    if mode != 'deterministic' and chat_fn is None:
        raise ValueError('LLM mode requires chat_fn')
    run_id = uuid.uuid4()
    kind = {'deterministic':'DETERMINISTIC', 'llm':'LLM', 'hybrid':'HYBRID'}[mode]
    try:
        with conn.transaction():
            # Validate source identity and content against the canonical database.
            if jurisdiction == 'FR':
                row = conn.execute('SELECT contenu FROM version WHERE id = %s', (source_id,)).fetchone()
            else:
                row = conn.execute('SELECT text FROM eu_provision WHERE provision_id = %s', (source_id,)).fetchone()
            if row is None or row[0] != source_text:
                raise ValueError('source not found or content differs from PostgreSQL')
            conn.execute('''INSERT INTO legal_obligation_run
                (run_id,pipeline_version,extractor_kind,provider,model,prompt_version,parameters)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)''',
                (run_id, PIPELINE_VERSION,kind,provider,model,PROMPT_VERSION if mode != 'deterministic' else None,
                 json.dumps({'mode':mode,'source_jurisdiction':jurisdiction,'source_id':source_id})))
            items = deterministic(source_text) if mode in ('deterministic','hybrid') else []
            if mode in ('llm','hybrid'):
                llm_items, _ = llm_extract(source_text, chat_fn)
                items += llm_items
            seen = set()
            count = 0
            for item in items:
                ob = item.obligation
                key = (ob['span_start'], ob['span_end'], ob['modality'], ob['action'])
                if key in seen:
                    continue
                seen.add(key)
                conn.execute('''INSERT INTO legal_obligation
                  (obligation_id,run_id,jurisdiction,legi_version_id,eu_provision_id,
                   source_checksum,source_excerpt,span_start,span_end,actor,modality,
                   action,object,conditions,exceptions,deadline,frequency,threshold,
                   territorial_scope,temporal_scope,confidence,evidence,raw_output)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                          %s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)''',
                  (uuid.uuid4(),run_id,jurisdiction,source_id if jurisdiction=='FR' else None,
                   source_id if jurisdiction=='EU' else None,checksum(source_text),ob['source_excerpt'],
                   ob['span_start'],ob['span_end'],ob['actor'],ob['modality'],ob['action'],
                   ob['object'],json.dumps(ob['conditions']),json.dumps(ob['exceptions']),
                   ob['deadline'],ob['frequency'],ob['threshold'],ob['territorial_scope'],
                   ob['temporal_scope'],item.confidence,
                   json.dumps([{'source_excerpt':ob['source_excerpt'],'span_start':ob['span_start'],
                                'span_end':ob['span_end'],'extractor':item.extractor}]),
                   json.dumps(item.raw_output) if item.raw_output is not None else None))
                count += 1
            conn.execute("UPDATE legal_obligation_run SET status='SUCCEEDED', finished_at=now() WHERE run_id=%s", (run_id,))
        return {'run_id':str(run_id),'obligations':count,'mode':mode,'source_checksum':checksum(source_text)}
    except Exception:
        conn.rollback()
        raise
