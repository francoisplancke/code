"""
Application Flask pour rechercher dans le corpus LEGI via PostgreSQL + pgvector.

Prerequis:
    pip install flask "psycopg[binary]" pgvector sentence-transformers numpy

Exemple:
    export LEGAL_DSN="postgresql://postgres:postgres@localhost:5432/legal"
    export LEGAL_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    export LEGAL_DEVICE="cuda"
    python3 app.py
"""

from __future__ import annotations

import os
from flask import Flask, abort, render_template, request

from search_interactive import LegiSearch, _format_chemin_hierarchique


app = Flask(__name__)

DSN = os.environ.get(
    "LEGAL_DSN",
    "postgresql://postgres:postgres@localhost:5432/legal",
)
MODEL_NAME = os.environ.get(
    "LEGAL_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
DEVICE = os.environ.get("LEGAL_DEVICE", "cuda")
ETAT = os.environ.get("LEGAL_ETAT", "VIGUEUR")

DEFAULT_K = int(os.environ.get("LEGAL_SEARCH_K", "10"))
DEFAULT_LEXICAL_WEIGHT = float(os.environ.get("LEGAL_LEXICAL_WEIGHT", "0.25"))

QUERY_LOG_RETENTION_DAYS = max(
    1, int(os.environ.get("LEGAL_QUERY_LOG_RETENTION_DAYS", "30"))
)
DATA_SOURCE_NAME = os.environ.get(
    "LEGAL_DATA_SOURCE_NAME",
    "DILA / Légifrance — corpus consolidé LEGI",
)
DATA_SOURCE_URL = os.environ.get(
    "LEGAL_DATA_SOURCE_URL",
    "https://www.data.gouv.fr/datasets/legi-codes-lois-et-reglements-consolides",
)
DATA_ARCHIVE = os.environ.get(
    "LEGAL_DATA_ARCHIVE",
    "Freemium_legi_global_20250713-140000.tar.gz",
)
DATA_DATE = os.environ.get("LEGAL_DATA_DATE", "2025-07-13")
OPERATOR_NAME = os.environ.get(
    "LEGAL_OPERATOR_NAME",
    "Exploitant du service — identité à renseigner avant mise en production",
)
PRIVACY_CONTACT = os.environ.get(
    "LEGAL_PRIVACY_CONTACT",
    "Contact confidentialité à renseigner avant mise en production",
)
PRIVACY_LEGAL_BASIS = os.environ.get(
    "LEGAL_PRIVACY_LEGAL_BASIS",
    "Intérêt légitime de l’exploitant pour la sécurité, la prévention des abus et le diagnostic du service (à valider selon votre situation).",
)
TEXT_TYPE_LABELS = {
    "ACCORD_FONCTION_PUBLIQUE": "Accord de la fonction publique",
    "ARRETE": "Arrêté",
    "AVIS": "Avis",
    "CIRCULAIRE": "Circulaire",
    "CODE": "Code",
    "CONSTITUTION": "Constitution",
    "CONVENTION": "Convention",
    "DECISION": "Décision",
    "DECRET": "Décret",
    "DECRET_LOI": "Décret-loi",
    "DELIBERATION": "Délibération",
    "LOI": "Loi",
    "LOI_CONSTIT": "Loi constitutionnelle",
    "LOI_ORGANIQUE": "Loi organique",
    "LOI_PROGRAMME": "Loi de programme",
    "ORDONNANCE": "Ordonnance",
    "RAPPORT": "Rapport",
}


print("⚡ Initialisation du moteur de recherche LEGI...")
searcher = LegiSearch(
    model_path=MODEL_NAME,
    dsn=DSN,
    device=DEVICE,
    etat=ETAT,
)


def _get_article_by_version_source_id(article_id: str):
    """Charge une version LEGI précise depuis PostgreSQL."""
    sql = """
        SELECT
            v.id AS version_id,
            v.source_id AS version_source_id,
            v.etat,
            v.date_debut,
            v.date_fin,
            v.contenu,
            v.nota,
            v.source_path,
            v.metadata AS version_metadata,
            u.id AS unite_id,
            u.source_id AS unite_source_id,
            u.type AS type_unite,
            u.numero,
            u.ordre,
            u.chemin,
            u.metadata AS unite_metadata,
            t.id AS texte_id,
            t.source_id AS texte_source_id,
            t.titre,
            t.type AS type_texte,
            t.metadata AS texte_metadata
        FROM version v
        JOIN unite u ON u.id = v.unite_id
        LEFT JOIN texte t ON t.id = u.texte_id
        WHERE v.source_id = %s
        LIMIT 1
    """

    with searcher.conn.cursor() as cur:
        cur.execute(sql, (article_id,))
        row = cur.fetchone()
        if not row:
            return None

        cols = [d.name for d in cur.description]
        data = dict(zip(cols, row))

    chemin = data.get("chemin") or []

    return {
        "id": data["version_source_id"],
        "version_id": str(data["version_id"]),
        "unite_id": str(data["unite_id"]),
        "unite_source_id": data.get("unite_source_id") or "",
        "num": data.get("numero") or "",
        "contenu": data.get("contenu") or "",
        "nota": data.get("nota") or "",
        "etat": data.get("etat") or "",
        "date_modification": str(data.get("date_debut") or ""),
        "date_debut": str(data.get("date_debut") or ""),
        "date_fin": str(data.get("date_fin") or ""),
        "chemin_hierarchique": chemin,
        "chemin_affichage": _format_chemin_hierarchique(chemin),
        "references": [],
        "metadata": {
            "texte_cid": data.get("texte_source_id") or "",
            "texte_titre": data.get("titre") or "Texte sans titre",
            "nature": data.get("type_texte") or "",
            "type_texte": data.get("type_texte") or "",
            "type_article": data.get("type_unite") or "ARTICLE",
            "ordre": data.get("ordre"),
            "source_xml": data.get("source_path") or "",
            "version_metadata": data.get("version_metadata") or {},
            "unite_metadata": data.get("unite_metadata") or {},
            "texte_metadata": data.get("texte_metadata") or {},
        },
    }

def _get_text_types():
    """Types de textes disponibles pour alimenter un filtre UI."""
    with searcher.conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT type
            FROM texte
            WHERE type IS NOT NULL AND type <> ''
            ORDER BY type
        """)
        types = [row[0] for row in cur.fetchall()]

    return [
        {
            "value": type_code,
            "label": TEXT_TYPE_LABELS.get(
                type_code,
                type_code.replace("_", " ").title()
            ),
        }
        for type_code in types
    ]

def _ensure_query_log_schema():
    with searcher.conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS search_query_log (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                query TEXT NOT NULL,
                ip_address INET
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS search_query_log_created_at_idx
            ON search_query_log (created_at)
        """)
    searcher.conn.commit()


def _purge_old_query_logs():
    with searcher.conn.cursor() as cur:
        cur.execute("""
            DELETE FROM search_query_log
            WHERE created_at < now() - (%s * interval '1 day')
        """, (QUERY_LOG_RETENTION_DAYS,))
    searcher.conn.commit()


def _log_search_query(query: str):
    with searcher.conn.cursor() as cur:
        cur.execute("""
            INSERT INTO search_query_log (query, ip_address)
            VALUES (%s, %s)
        """, (query, request.remote_addr))
    searcher.conn.commit()


_ensure_query_log_schema()
_purge_old_query_logs()


@app.route("/", methods=["GET", "POST"])
def index():
    # GET et POST sont acceptés pour rendre les filtres facilement partageables
    # dans l'URL tout en restant compatible avec l'ancien formulaire POST.
    values = request.values

    query = (values.get("query") or "").strip()
    texte_source_id = (values.get("texte") or "").strip() or None
    type_texte = (values.get("type_texte") or "").strip() or None

    try:
        k = max(1, min(int(values.get("k", DEFAULT_K)), 50))
    except (TypeError, ValueError):
        k = DEFAULT_K

    try:
        lexical_weight = float(
            values.get("lexical_weight", DEFAULT_LEXICAL_WEIGHT)
        )
    except (TypeError, ValueError):
        lexical_weight = DEFAULT_LEXICAL_WEIGHT

    lexical_weight = max(0.0, min(lexical_weight, 1.0))
    vector_only = values.get("vector_only") in {"1", "true", "on", "yes"}

    results = []
    if query:
        _log_search_query(query)
        _purge_old_query_logs()
        results = searcher.search(
            query,
            k=k,
            texte_source_id=texte_source_id,
            type_texte=type_texte,
            hybrid=not vector_only,
            lexical_weight=lexical_weight,
        )

    return render_template(
        "index.html",
        query=query,
        results=results,
        texte=texte_source_id or "",
        type_texte=type_texte or "",
        text_types=_get_text_types(),
        k=k,
        vector_only=vector_only,
        lexical_weight=lexical_weight,
        etat=ETAT,
    )


@app.route("/article/<article_id>")
def view_article(article_id):
    # article_id = source_id de version, typiquement LEGIARTI...
    article = _get_article_by_version_source_id(article_id)
    if not article:
        abort(404, description="Article introuvable")

    # Recherche de dispositions proches dans tout LEGI.
    # On exclut ensuite la version affichée elle-même.
    similar_results = searcher.search(
        article["contenu"],
        k=8,
        hybrid=True,
        lexical_weight=DEFAULT_LEXICAL_WEIGHT,
    )
    related = [
        result
        for result in similar_results
        if result["id"] != article_id
    ][:5]

    return render_template(
        "article.html",
        article=article,
        related=related,
    )


@app.route("/texte/<texte_source_id>")
def view_text(texte_source_id):
    """Liste les versions VIGUEUR d'un texte (code, loi, décret...)."""
    with searcher.conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, titre, type, source_id
            FROM texte
            WHERE source_id = %s
            LIMIT 1
            """,
            (texte_source_id,),
        )
        texte_row = cur.fetchone()
        if not texte_row:
            abort(404, description="Texte introuvable")

        texte = {
            "id": str(texte_row[0]),
            "titre": texte_row[1],
            "type": texte_row[2],
            "source_id": texte_row[3],
        }

        cur.execute(
            """
            SELECT
                v.source_id,
                u.numero,
                v.date_debut,
                v.date_fin,
                u.ordre
            FROM version v
            JOIN unite u ON u.id = v.unite_id
            JOIN texte t ON t.id = u.texte_id
            WHERE t.source_id = %s
              AND v.etat = %s
            ORDER BY u.ordre NULLS LAST, u.numero, v.date_debut
            """,
            (texte_source_id, ETAT),
        )

        articles = [
            {
                "id": row[0],
                "num": row[1] or "",
                "date_debut": str(row[2] or ""),
                "date_fin": str(row[3] or ""),
                "ordre": row[4],
            }
            for row in cur.fetchall()
        ]

    # Ce template est optionnel. Si tu ne le crées pas immédiatement,
    # la route principale et la page article restent utilisables.
    return render_template(
        "texte.html",
        texte=texte,
        articles=articles,
    )


@app.route("/mentions")
def legal_notices():
    return render_template(
        "mentions.html",
        data_source_name=DATA_SOURCE_NAME,
        data_source_url=DATA_SOURCE_URL,
        data_archive=DATA_ARCHIVE,
        data_date=DATA_DATE,
        operator_name=OPERATOR_NAME,
        privacy_contact=PRIVACY_CONTACT,
        privacy_legal_basis=PRIVACY_LEGAL_BASIS,
        query_log_retention_days=QUERY_LOG_RETENTION_DAYS,
    )


@app.context_processor
def inject_app_context():
    return {
        "app_corpus_name": "LEGI",
        "app_search_state": ETAT,
        "app_data_source_name": DATA_SOURCE_NAME,
        "app_data_source_url": DATA_SOURCE_URL,
        "app_data_archive": DATA_ARCHIVE,
        "app_data_date": DATA_DATE,
        "app_query_log_retention_days": QUERY_LOG_RETENTION_DAYS,
    }


if __name__ == "__main__":
    # use_reloader=False évite de charger deux fois le modèle CUDA
    # avec le reloader du serveur de développement Flask.
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False,
    )
