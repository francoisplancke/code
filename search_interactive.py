"""CLI/façade compatible pour la recherche LEGI PostgreSQL + pgvector.

R1 sépare désormais connexion DB, chargement des embeddings et moteur de retrieval.
L'API publique historique ``LegiSearch`` est conservée pour ``app.py``.
"""
from __future__ import annotations

import argparse
from typing import Optional

from legal.db import EmbeddingModelRepository, PostgresDatabase, safe_dsn
from legal.retrieval import (
    HybridSearchEngine,
    SentenceTransformerEmbedder,
    format_chemin_hierarchique,
)

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/legal"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Alias de compatibilité avec app.py et les imports existants.
_format_chemin_hierarchique = format_chemin_hierarchique


class LegiSearch:
    """Façade compatible avec l'ancien moteur de recherche."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        dsn: str = DEFAULT_DSN,
        device: Optional[str] = None,
        etat: str = "VIGUEUR",
        *,
        database: PostgresDatabase | None = None,
        embedder: SentenceTransformerEmbedder | None = None,
    ):
        self.dsn = dsn
        self.model_name = model_path
        self.etat = etat

        print("🔧 Chargement du système de recherche...")
        print(f"   → PostgreSQL : {safe_dsn(dsn)}")
        print(f"   → Modèle     : {model_path}")
        if device:
            print(f"   → Device     : {device}")

        self.database = database or PostgresDatabase(dsn)
        # Connexion conservée pour compatibilité avec app.py R0.
        self.conn = self.database.connection

        self.embedder = embedder or SentenceTransformerEmbedder(model_path, device=device)
        self.model = self.embedder.model  # compatibilité avec du code externe éventuel
        self.dimension = self.embedder.dimension

        repo = EmbeddingModelRepository(self.conn)
        record = repo.get_by_name(model_path)
        if record is None:
            raise RuntimeError(
                f"Modèle '{model_path}' absent de embedding_model. "
                "Vectorisez d'abord la base avec ce modèle."
            )
        self.model_id = record.id
        self.normalize = record.normalize
        if record.dimension != self.dimension:
            raise RuntimeError(
                f"Dimension incompatible: modèle={self.dimension}, base={record.dimension}."
            )

        self.engine = HybridSearchEngine(
            connection=self.conn,
            embedder=self.embedder,
            model_id=self.model_id,
            dimension=self.dimension,
            normalize=self.normalize,
            etat=self.etat,
        )
        count = repo.count_versions(self.model_id, self.etat)
        print(f"✅ Système prêt : {count:,} versions {self.etat} vectorisées\n".replace(',', ' '))

    @staticmethod
    def _safe_dsn(dsn: str) -> str:
        return safe_dsn(dsn)

    def close(self):
        if getattr(self, "database", None) is not None:
            self.database.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _encode(self, text: str):
        return self.embedder.encode(text, normalize=self.normalize)

    def search(self, *args, **kwargs):
        return self.engine.search(*args, **kwargs)
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
