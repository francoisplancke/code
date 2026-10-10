"""Read-only, cached PostgreSQL corpus statistics."""
from __future__ import annotations

import os
import threading
import time

from psycopg import connect

# Each query is independent, so a missing optional table does not hide the rest.
QUERIES = {
    'fr': {
        'totals': "SELECT (SELECT count(*) FROM texte) textes, (SELECT count(*) FROM texte WHERE type='CODE') codes, (SELECT count(*) FROM unite WHERE type='ARTICLE') articles, (SELECT count(*) FROM version) versions, (SELECT count(*) FROM version WHERE etat='VIGUEUR') vigueur, (SELECT count(*) FROM relation_juridique) liens, (SELECT count(*) FROM version_embedding) embeddings",
        'types': "SELECT coalesce(type,'INCONNU') label, count(*) n FROM texte GROUP BY 1 ORDER BY n DESC LIMIT 20",
        'relations': "SELECT coalesce(type_relation,'INCONNU') label, count(*) n FROM relation_juridique GROUP BY 1 ORDER BY n DESC LIMIT 20",
        'etats': "SELECT coalesce(etat,'INCONNU') label, count(*) n FROM version GROUP BY 1 ORDER BY n DESC",
        'codes': "SELECT t.titre label, count(u.id) n FROM texte t LEFT JOIN unite u ON u.texte_id=t.id AND u.type='ARTICLE' WHERE t.type='CODE' GROUP BY t.id,t.titre ORDER BY n DESC LIMIT 30",
        'models': "SELECT m.name label, m.dimension, count(e.version_id) n FROM embedding_model m LEFT JOIN version_embedding e ON e.model_id=m.id GROUP BY m.id,m.name,m.dimension ORDER BY n DESC",
        'imports': "SELECT source, started_at, finished_at, stats FROM import_log ORDER BY started_at DESC LIMIT 1",
    },
    'eu': {
        'totals': "SELECT (SELECT count(*) FROM eu_act) actes, (SELECT count(*) FROM eu_act WHERE act_type='DIRECTIVE') directives, (SELECT count(*) FROM eu_provision) dispositions, (SELECT count(*) FROM eu_provision WHERE kind='ARTICLE') articles, (SELECT count(*) FROM eu_provision WHERE parent_id IS NOT NULL) liens_hierarchiques, (SELECT count(*) FROM eu_provision WHERE btrim(text)='') sans_texte, (SELECT count(*) FROM eu_act a WHERE NOT EXISTS (SELECT 1 FROM eu_provision p WHERE p.celex=a.celex)) sans_dispositions",
        'types': "SELECT coalesce(act_type,'INCONNU') label, count(*) n FROM eu_act GROUP BY 1 ORDER BY n DESC",
        'kinds': "SELECT coalesce(kind,'INCONNU') label, count(*) n FROM eu_provision GROUP BY 1 ORDER BY n DESC",
    },
}

_CACHE = {}
_LOCK = threading.Lock()


def collect(dsn: str, ttl: int | None = None, connect_fn=connect):
    if not dsn:
        raise ValueError('LEGAL_DSN est requis pour les statistiques')
    if ttl is None:
        ttl = max(0, int(os.getenv('LEGAL_STATS_CACHE_SECONDS', '900')))
    now = time.monotonic()
    with _LOCK:
        if ttl and dsn in _CACHE and now - _CACHE[dsn][0] < ttl:
            return _CACHE[dsn][1]
        result = {'fr': {}, 'eu': {}, 'errors': []}
        # New connection: never reuse the search connection shared by Flask workers.
        with connect_fn(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute('SET statement_timeout = 30000')
                cur.execute('SET default_transaction_read_only = on')
                for corpus, queries in QUERIES.items():
                    for key, sql in queries.items():
                        try:
                            cur.execute(sql)
                            names = [d.name for d in cur.description]
                            rows = [dict(zip(names, row)) for row in cur.fetchall()]
                            result[corpus][key] = rows[0] if key == 'totals' else rows
                        except Exception as exc:
                            result[corpus][key] = None
                            result['errors'].append(f'{corpus}.{key}: {type(exc).__name__}')
        _CACHE[dsn] = (now, result)
        return result
