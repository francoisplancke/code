"""
Recherche interactive dans le corpus LEGI stocke dans PostgreSQL + pgvector.

Prerequis:
    pip install "psycopg[binary]" pgvector sentence-transformers numpy

Exemple:
    python3 search_interactive.py \
      --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
      --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
      --device cuda
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from typing import Dict, List, Optional

try:
    import numpy as np
    import psycopg
    from pgvector.psycopg import register_vector
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    raise SystemExit(
        'Module manquant. Installez avec: pip install "psycopg[binary]" '
        'pgvector sentence-transformers numpy'
    ) from exc


DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/legal"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"



def _format_chemin_hierarchique(value) -> str:
    """Retourne un chemin lisible depuis unite.chemin (JSONB LEGI)."""
    if not value:
        return ""

    data = value

    # Cas texte JSON / représentation Python.
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

    titles = []

    if isinstance(data, list):
        for item in data:
            current = item

            # Certaines anciennes/importations stockent chaque élément
            # de la liste comme chaîne représentant un dictionnaire.
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

    # Dédupliquer les titres consécutifs éventuels.
    cleaned = []
    for title in titles:
        if title and (not cleaned or cleaned[-1] != title):
            cleaned.append(title)

    return " > ".join(cleaned)


def _lexical_query(query: str) -> str:
    """Normalise legerement la requete pour le classement lexical."""
    return " ".join((query or "").split()).strip()


class LegiSearch:
    """Moteur de recherche semantique PostgreSQL + pgvector."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        dsn: str = DEFAULT_DSN,
        device: Optional[str] = None,
        etat: str = "VIGUEUR",
    ):
        self.dsn = dsn
        self.model_name = model_path
        self.etat = etat

        print("🔧 Chargement du système de recherche...")
        print(f"   → PostgreSQL : {self._safe_dsn(dsn)}")
        print(f"   → Modèle     : {model_path}")
        if device:
            print(f"   → Device     : {device}")

        self.model = SentenceTransformer(model_path, device=device) if device else SentenceTransformer(model_path)
        self.dimension = int(self.model.get_embedding_dimension())

        self.conn = psycopg.connect(dsn)
        register_vector(self.conn)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, dimension, normalize
                FROM embedding_model
                WHERE name = %s
                """,
                (model_path,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(
                    f"Modèle '{model_path}' absent de embedding_model. "
                    "Vectorisez d'abord la base avec ce modèle."
                )
            self.model_id = int(row[0])
            db_dimension = int(row[1])
            self.normalize = bool(row[2])

            if db_dimension != self.dimension:
                raise RuntimeError(
                    f"Dimension incompatible: modèle={self.dimension}, base={db_dimension}."
                )

            cur.execute(
                """
                SELECT COUNT(*)
                FROM version_embedding ve
                JOIN version v ON v.id = ve.version_id
                WHERE ve.model_id = %s AND v.etat = %s
                """,
                (self.model_id, self.etat),
            )
            count = int(cur.fetchone()[0])

        print(f"✅ Système prêt : {count:,} versions {self.etat} vectorisées\n".replace(',', ' '))

    @staticmethod
    def _safe_dsn(dsn: str) -> str:
        # Evite d'afficher le mot de passe dans les logs.
        if "://" not in dsn or "@" not in dsn:
            return dsn
        prefix, rest = dsn.split("://", 1)
        credentials, host = rest.rsplit("@", 1)
        if ":" in credentials:
            user = credentials.split(":", 1)[0]
            return f"{prefix}://{user}:***@{host}"
        return dsn

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _encode(self, text: str):
        return self.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize,
        ).astype(np.float32)

    @staticmethod
    def _row_to_article(row: Dict) -> Dict:
        chemin = row.get("chemin") or []
        if isinstance(chemin, str):
            try:
                chemin = json.loads(chemin)
            except Exception:
                chemin = [chemin]

        metadata = {
            "texte_cid": row.get("texte_source_id") or "",
            "texte_titre": row.get("titre") or "",
            "nature": row.get("type_texte") or "",
            "type_article": row.get("type_unite") or "ARTICLE",
            "date_debut": str(row.get("date_debut") or ""),
            "date_fin": str(row.get("date_fin") or ""),
            "source_xml": row.get("source_path") or "",
        }

        return {
            # Compatibilite avec l'ancienne interface / Flask.
            "id": row.get("version_source_id"),
            "version_id": str(row.get("version_id")),
            "unite_id": str(row.get("unite_id")),
            "num": row.get("numero") or "",
            "contenu": row.get("contenu") or "",
            "etat": row.get("etat") or "",
            "date_modification": str(row.get("date_debut") or ""),
            "date_fin": str(row.get("date_fin") or ""),
            "titre_modification": None,
            "chemin_hierarchique": chemin,
            "niveau_profondeur": len(chemin),
            "references": [],
            "metadata": metadata,
        }

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
    ):
        """
        Recherche semantique dans les versions VIGUEUR.

        En mode hybride, on combine :
          - similarite cosinus pgvector ;
          - pertinence lexicale PostgreSQL via websearch_to_tsquery / ts_rank_cd.

        lexical_weight=0.25 signifie 75 % vectoriel / 25 % lexical.
        """
        query = (query or "").strip()
        if not query:
            return []

        lexical_weight = max(0.0, min(float(lexical_weight), 1.0))
        vector_weight = 1.0 - lexical_weight

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]

        filters = ["ve.model_id = %s", "v.etat = %s"]
        filter_params = [self.model_id, self.etat]

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

        # On recupere davantage de candidats HNSW puis on les rerange lexicalement.
        candidate_k = max(k, k * max(1, int(candidate_multiplier))) if hybrid else k

        if hybrid:
            lex_query = _lexical_query(query)
            # "simple" conserve les formes juridiques/francaises sans stemming agressif.
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
            params = [
                query_embedding,
                *filter_params,
                query_embedding,
                candidate_k,
                lex_query,
            ]
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

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        if hybrid and rows:
            # ts_rank_cd n'est pas borne a 1. Normalisation locale robuste sur les candidats.
            max_lex = max(float(r.get("lexical_score") or 0.0) for r in rows)
            for r in rows:
                vector_score = float(r.get("vector_score") or 0.0)
                raw_lex = float(r.get("lexical_score") or 0.0)
                lexical_score = (raw_lex / max_lex) if max_lex > 0 else 0.0
                r["lexical_score_normalized"] = lexical_score
                r["score"] = vector_weight * vector_score + lexical_weight * lexical_score

            rows.sort(key=lambda r: r["score"], reverse=True)
            rows = rows[:k]
        else:
            for r in rows:
                r["score"] = float(r.get("vector_score") or 0.0)

        results = []
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
                "chemin_affichage": _format_chemin_hierarchique(row["chemin"]),
                "references": [],
                "metadata": {
                    "texte_cid": row["texte_source_id"] or "",
                    "texte_titre": row["titre"] or "",
                    "nature": row["type_texte"] or "",
                    "type_texte": row["type_texte"] or "",
                },
            }

            results.append({
                "article": article,
                "score": score,
                "vector_score": float(row.get("vector_score") or 0.0),
                "lexical_score": float(
                    row.get("lexical_score_normalized")
                    if hybrid
                    else 0.0
                ),
                "num": article["num"],
                "id": article["id"],
            })

        return results

    def display_results(self, results, show_full_content: bool = False):
        if not results:
            print("❌ Aucun résultat trouvé")
            return

        print(f"\n{'=' * 80}")
        print(f"📊 {len(results)} résultat(s) trouvé(s)")
        print("=" * 80)

        for i, result in enumerate(results, 1):
            article = result["article"]
            meta = article["metadata"]
            score = result["score"]
            titre = meta.get("texte_titre") or "Texte sans titre"
            nature = meta.get("nature") or ""

            print(f"\n{i}. 📌 {titre} — Article {article['num']} (score: {score:.3f})")
            print(f"   ⚖️  {nature} | État: {article['etat']} | Début: {article['date_modification']}")
            print(f"   🔑 Version: {article['id']} | Texte: {meta.get('texte_cid', '')}")

            chemin = article.get("chemin_hierarchique") or []
            if chemin:
                chemin_txt = " > ".join(str(x) for x in chemin)
                if len(chemin_txt) > 150:
                    chemin_txt = "..." + chemin_txt[-147:]
                print(f"   📂 {chemin_txt}")

            if show_full_content:
                print("\n   📝 Contenu complet :")
                print("   " + "─" * 76)
                for line in article["contenu"].splitlines():
                    print("   " + line)
                print("   " + "─" * 76)
            else:
                preview = article["contenu"][:400].replace("\n", " ")
                print(f"   📝 {preview}{'...' if len(article['contenu']) > 400 else ''}")

    def display_analysis(self, analysis):
        if analysis is None:
            print("❌ Aucune analyse disponible")
            return

        print(f"\n{'=' * 80}")
        print(f"📊 ANALYSE DU SUJET : {analysis['topic']}")
        print("=" * 80)
        print(f"\n📚 {analysis['num_articles']} résultats pertinents")

        print("\n📄 Types de texte :")
        for name, count in sorted(analysis["types"].items(), key=lambda x: x[1], reverse=True):
            print(f"   {count:3d} → {name}")

        print("\n📚 Textes les plus représentés :")
        for name, count in sorted(analysis["textes"].items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   {count:3d} → {name[:70]}")

        print(f"\n📝 Longueur moyenne : {analysis['longueur_moyenne']:.0f} caractères")
        print("\n🔝 Top 5 :")
        for i, result in enumerate(analysis["articles"][:5], 1):
            a = result["article"]
            print(
                f"   {i}. {a['metadata'].get('texte_titre')} — "
                f"Article {a['num']} ({result['score']:.3f})"
            )


def interactive_mode(searcher: LegiSearch):
    print("\n" + "=" * 80)
    print("🔍 MODE INTERACTIF - POSTGRESQL + PGVECTOR")
    print("=" * 80)
    print("\nCommandes :")
    print("  - question libre")
    print("  - analyse [sujet]")
    print("  - similaires [article]                  ex: similaires L1132-1")
    print("  - similaires [CID_TEXTE] [article]      ex: similaires LEGITEXT000006072050 L1132-1")
    print("  - full")
    print("  - quit")

    show_full = False
    while True:
        try:
            raw = input("\n💬 Votre requête : ").strip()
            if not raw:
                continue
            if raw.lower() == "quit":
                print("👋 Au revoir !")
                break
            if raw.lower() == "full":
                show_full = not show_full
                print(f"{'✅' if show_full else '❌'} Contenu complet : {show_full}")
                continue
            if raw.lower().startswith("analyse "):
                topic = raw[8:].strip()
                searcher.display_analysis(searcher.analyze_topic(topic, k=20))
                continue
            if raw.lower().startswith("similaires "):
                args = raw[11:].strip().split()
                if len(args) == 1:
                    results = searcher.find_related_articles(args[0], k=5)
                elif len(args) >= 2:
                    results = searcher.find_related_articles(args[-1], k=5, texte_source_id=args[0])
                else:
                    results = []
                searcher.display_results(results, show_full)
                continue

            searcher.display_results(searcher.search(raw, k=10), show_full)
        except KeyboardInterrupt:
            print("\n👋 Au revoir !")
            break
        except Exception as exc:
            print(f"❌ Erreur : {exc}")


def build_arg_parser():
    p = argparse.ArgumentParser(description="Recherche LEGI PostgreSQL + pgvector")
    p.add_argument("--dsn", default=DEFAULT_DSN)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--device", default=None, help="cpu, cuda, cuda:0...")
    p.add_argument("--etat", default="VIGUEUR")
    p.add_argument("--query", help="Effectue une seule recherche puis quitte")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--min-score", type=float, default=0.30)
    p.add_argument("--texte", help="Filtre LEGITEXT...")
    p.add_argument("--type-texte", help="Filtre CODE, LOI, DECRET...")
    p.add_argument("--full", action="store_true")
    p.add_argument(
        "--vector-only",
        action="store_true",
        help="Désactive le reranking lexical et utilise uniquement pgvector",
    )
    p.add_argument(
        "--lexical-weight",
        type=float,
        default=0.25,
        help="Poids du signal lexical dans le score hybride (défaut: 0.25)",
    )
    return p


def main():
    args = build_arg_parser().parse_args()
    with LegiSearch(args.model, args.dsn, args.device, args.etat) as searcher:
        if args.query:
            results = searcher.search(
            args.query,
            k=args.k,
                min_score=args.min_score,
                texte_source_id=args.texte,
                type_texte=args.type_texte,
            
            hybrid=not args.vector_only,
            lexical_weight=args.lexical_weight,
        )
            searcher.display_results(results, args.full)
        else:
            interactive_mode(searcher)


# Alias temporaire de compatibilite avec app.py existant.
CodeDuTravailSearch = LegiSearch


if __name__ == "__main__":
    main()
