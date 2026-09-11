from __future__ import annotations

import ast
import json
from typing import Any


def format_chemin_hierarchique(value) -> str:
    """Retourne un chemin lisible depuis unite.chemin (JSONB LEGI)."""
    if not value:
        return ""
    data = value
    if isinstance(data, str):
        stripped = data.strip()
        if not stripped:
            return ""
        try:
            data = json.loads(stripped)
        except Exception:
            try:
                data = ast.literal_eval(stripped)
            except Exception:
                return stripped
    if isinstance(data, dict):
        data = [data]

    titles: list[str] = []
    if isinstance(data, list):
        for item in data:
            current = item
            if isinstance(current, str):
                s = current.strip()
                if not s:
                    continue
                try:
                    current = json.loads(s)
                except Exception:
                    try:
                        current = ast.literal_eval(s)
                    except Exception:
                        current = s
            if isinstance(current, dict):
                title = (
                    current.get("titre")
                    or current.get("title")
                    or current.get("libelle")
                    or ""
                )
                title = str(title).strip()
                if title:
                    titles.append(title)
            elif current:
                s = str(current).strip()
                if s:
                    titles.append(s)
    elif data:
        titles.append(str(data).strip())

    cleaned: list[str] = []
    for title in titles:
        if title and (not cleaned or cleaned[-1] != title):
            cleaned.append(title)
    return " > ".join(cleaned)


def lexical_query(query: str) -> str:
    """Normalise légèrement la requête pour le classement lexical."""
    return " ".join((query or "").split()).strip()


def _score_hybrid_rows(rows: list[dict], lexical_weight: float, k: int) -> list[dict]:
    """Reproduit exactement la normalisation/scoring historique."""
    if not rows:
        return rows
    lexical_weight = max(0.0, min(float(lexical_weight), 1.0))
    vector_weight = 1.0 - lexical_weight
    max_lex = max(float(r.get("lexical_score") or 0.0) for r in rows)
    for row in rows:
        vector_score = float(row.get("vector_score") or 0.0)
        raw_lex = float(row.get("lexical_score") or 0.0)
        normalized = (raw_lex / max_lex) if max_lex > 0 else 0.0
        row["lexical_score_normalized"] = normalized
        row["score"] = vector_weight * vector_score + lexical_weight * normalized
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:k]


class HybridSearchEngine:
    """Recherche PostgreSQL/pgvector, indépendante du chargement du modèle."""

    def __init__(
        self,
        connection: Any,
        embedder: Any,
        model_id: int,
        dimension: int,
        normalize: bool,
        etat: str = "VIGUEUR",
    ):
        self.connection = connection
        self.embedder = embedder
        self.model_id = int(model_id)
        self.dimension = int(dimension)
        self.normalize = bool(normalize)
        self.etat = etat

    def search(
        self,
        query: str,
        k: int = 10,
        min_score: float = 0.0,
        texte_source_id: str | None = None,
        type_texte: str | None = None,
        hybrid: bool = True,
        lexical_weight: float = 0.25,
        candidate_multiplier: int = 8,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []

        lexical_weight = max(0.0, min(float(lexical_weight), 1.0))
        query_embedding = self.embedder.encode(query, normalize=self.normalize)

        filters = ["ve.model_id = %s", "v.etat = %s"]
        filter_params: list[Any] = [self.model_id, self.etat]
        if texte_source_id:
            filters.append("t.source_id = %s")
            filter_params.append(texte_source_id)
        if type_texte:
            filters.append("t.type = %s")
            filter_params.append(type_texte.upper())
        where_sql = " AND ".join(filters)
        distance_expr = (
            f"ve.embedding::vector({self.dimension}) "
            f"<=> %s::vector({self.dimension})"
        )
        candidate_k = max(k, k * max(1, int(candidate_multiplier))) if hybrid else k

        if hybrid:
            lex_query = lexical_query(query)
            lexical_expr = """
                ts_rank_cd(
                    to_tsvector(
                        'simple',
                        concat_ws(
                            ' ',
                            coalesce(t.titre, ''),
                            coalesce(u.numero, ''),
                            coalesce(v.contenu, '')
                        )
                    ),
                    websearch_to_tsquery('simple', %s)
                )
            """
            sql = f"""
                WITH candidates AS (
                    SELECT
                        v.id AS version_id,
                        v.source_id AS version_source_id,
                        v.etat,
                        v.date_debut,
                        v.date_fin,
                        v.contenu,
                        u.chemin,
                        u.id AS unite_id,
                        u.source_id AS unite_source_id,
                        u.numero,
                        t.id AS texte_id,
                        t.source_id AS texte_source_id,
                        t.titre,
                        t.type AS type_texte,
                        ({distance_expr}) AS distance
                    FROM version_embedding ve
                    JOIN version v ON v.id = ve.version_id
                    JOIN unite u ON u.id = v.unite_id
                    JOIN texte t ON t.id = u.texte_id
                    WHERE {where_sql}
                    ORDER BY {distance_expr}
                    LIMIT %s
                )
                SELECT
                    c.*,
                    (1.0 - c.distance) AS vector_score,
                    ({lexical_expr}) AS lexical_score
                FROM candidates c
                JOIN texte t ON t.id = c.texte_id
                JOIN unite u ON u.id = c.unite_id
                JOIN version v ON v.id = c.version_id
            """
            params = [query_embedding, *filter_params, query_embedding, candidate_k, lex_query]
        else:
            sql = f"""
                SELECT
                    v.id AS version_id,
                    v.source_id AS version_source_id,
                    v.etat,
                    v.date_debut,
                    v.date_fin,
                    v.contenu,
                    u.chemin,
                    u.id AS unite_id,
                    u.source_id AS unite_source_id,
                    u.numero,
                    t.id AS texte_id,
                    t.source_id AS texte_source_id,
                    t.titre,
                    t.type AS type_texte,
                    ({distance_expr}) AS distance,
                    (1.0 - ({distance_expr})) AS vector_score,
                    0.0::double precision AS lexical_score
                FROM version_embedding ve
                JOIN version v ON v.id = ve.version_id
                JOIN unite u ON u.id = v.unite_id
                JOIN texte t ON t.id = u.texte_id
                WHERE {where_sql}
                ORDER BY {distance_expr}
                LIMIT %s
            """
            params = [
                query_embedding,
                query_embedding,
                query_embedding,
                *filter_params,
                k,
            ]

        with self.connection.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        if hybrid:
            rows = _score_hybrid_rows(rows, lexical_weight, k)
        else:
            for row in rows:
                row["score"] = float(row.get("vector_score") or 0.0)

        results: list[dict] = []
        for row in rows:
            score = float(row["score"])
            if score < min_score:
                continue
            article = {
                "id": row["version_source_id"],
                "version_id": row["version_id"],
                "unite_id": row["unite_id"],
                "unite_source_id": row["unite_source_id"],
                "num": row["numero"] or "",
                "contenu": row["contenu"] or "",
                "etat": row["etat"] or "",
                "date_modification": str(row["date_debut"] or ""),
                "date_debut": str(row["date_debut"] or ""),
                "date_fin": str(row["date_fin"] or ""),
                "chemin_hierarchique": row["chemin"],
                "chemin_affichage": format_chemin_hierarchique(row["chemin"]),
                "references": [],
                "metadata": {
                    "texte_cid": row["texte_source_id"] or "",
                    "texte_titre": row["titre"] or "",
                    "nature": row["type_texte"] or "",
                    "type_texte": row["type_texte"] or "",
                },
            }
            results.append(
                {
                    "article": article,
                    "score": score,
                    "vector_score": float(row.get("vector_score") or 0.0),
                    "lexical_score": float(
                        row.get("lexical_score_normalized") if hybrid else 0.0
                    ),
                    "num": article["num"],
                    "id": article["id"],
                }
            )
        return results
