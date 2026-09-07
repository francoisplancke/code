"""
Interface de recherche interactive pour le Code du travail
Permet de tester et valider la qualité du système
"""

from sentence_transformers import SentenceTransformer
import faiss
import json
from pathlib import Path
import numpy as np


class CodeDuTravailSearch:
    """Système de recherche dans le Code du travail"""
    
    def __init__(self, model_path: str, vectorized_dir: str = "./code_travail_vectorized"):
        """
        Initialise le système de recherche
        
        Args:
            model_path: Chemin vers le modèle (local ou nom HuggingFace)
            vectorized_dir: Dossier contenant l'index et métadonnées
        """
        self.vectorized_dir = Path(vectorized_dir)
        
        print("🔧 Chargement du système de recherche...")
        
        # Charger le modèle
        print(f"   → Modèle : {model_path}")
        self.model = SentenceTransformer(model_path)
        
        # Charger l'index FAISS
        print(f"   → Index FAISS...")
        self.index = faiss.read_index(str(self.vectorized_dir / "faiss_index.bin"))
        
        # Charger les métadonnées
        print(f"   → Métadonnées...")
        with open(self.vectorized_dir / "articles_metadata.json", 'r', encoding='utf-8') as f:
            self.articles = json.load(f)

        with open(self.vectorized_dir / "articles_metadata.json", 'r', encoding='utf-8') as f:
            self.articles = json.load(f)

        # Ajout pour accès direct ultra-rapide
        self.articles_by_id = {art['id']: art for art in self.articles}
        print(f"✅ Système prêt : {len(self.articles)} articles indexés\n")

    def get_article_by_id(self, article_id):
        return self.articles_by_id.get(article_id)            


    def search(self, query: str, k: int = 10, min_score: float = 0.3):
        """
        Recherche sémantique
        
        Args:
            query: Question ou texte à rechercher
            k: Nombre de résultats
            min_score: Score minimum de pertinence (0-1)
        
        Returns:
            Liste de résultats avec articles et scores
        """
        # Vectoriser la requête
        query_embedding = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        
        # Rechercher
        distances, indices = self.index.search(query_embedding, k)
        
        # Filtrer et formater les résultats
        results = []
        for idx, score in zip(indices[0], distances[0]):
            if score >= min_score:
                article = self.articles[idx]
                results.append({
                    'article': article,
                    'score': float(score),
                    'num': article['num'],
                    'id': article['id']
                })
        
        return results
    
    def display_results(self, results, show_full_content: bool = False):
        """Affiche les résultats de recherche de manière formatée"""
        
        if not results:
            print("❌ Aucun résultat trouvé")
            return
        
        print(f"\n{'='*70}")
        print(f"📊 {len(results)} résultat(s) trouvé(s)")
        print('='*70)
        
        for i, result in enumerate(results, 1):
            article = result['article']
            score = result['score']
            
            print(f"\n{i}. 📌 Article {article['num']} (score: {score:.3f})")
            print(f"   ID: {article['id']}")
            
            # Chemin hiérarchique
            if article['chemin_hierarchique']:
                chemin = ' > '.join(article['chemin_hierarchique'])
                # Limiter la longueur pour l'affichage
                if len(chemin) > 100:
                    chemin = '...' + chemin[-97:]
                print(f"   📂 {chemin}")
            
            # État et date
            print(f"   ⚖️  État: {article['etat']} | Date: {article['date_modification']}")
            
            # Contenu
            if show_full_content:
                print(f"\n   📝 Contenu complet :")
                print("   " + "─"*66)
                for line in article['contenu'].split('\n'):
                    print(f"   {line}")
                print("   " + "─"*66)
            else:
                contenu_preview = article['contenu'][:300].replace('\n', ' ')
                print(f"   📝 {contenu_preview}...")
            
            # Références
            if article['references']:
                print(f"   🔗 {len(article['references'])} référence(s) vers d'autres articles")
    
    def find_related_articles(self, article_num: str, k: int = 5):
        """
        Trouve les articles similaires à un article donné
        
        Args:
            article_num: Numéro de l'article (ex: "L1132-1")
            k: Nombre d'articles similaires à retourner
        """
        # Trouver l'article
        article = None
        article_idx = None
        for idx, art in enumerate(self.articles):
            if art['num'] == article_num:
                article = art
                article_idx = idx
                break
        
        if article is None:
            print(f"❌ Article {article_num} introuvable")
            return []
        
        # Rechercher avec le contenu de l'article comme requête
        query = f"{article['num']} {article['contenu'][:500]}"
        results = self.search(query, k=k+1)  # +1 car l'article lui-même sera dans les résultats
        
        # Exclure l'article lui-même
        results = [r for r in results if r['num'] != article_num][:k]
        
        return results
    
    def analyze_topic(self, topic: str, k: int = 20):
        """
        Analyse approfondie d'un sujet
        
        Args:
            topic: Sujet à analyser (ex: "discrimination", "télétravail")
            k: Nombre d'articles à récupérer
        
        Returns:
            Analyse structurée avec statistiques
        """
        results = self.search(topic, k=k, min_score=0.4)
        
        if not results:
            return None
        
        # Statistiques
        sections = {}
        etats = {}
        longueurs = []
        
        for result in results:
            article = result['article']
            
            # Par section
            if article['chemin_hierarchique']:
                section = article['chemin_hierarchique'][0]
                sections[section] = sections.get(section, 0) + 1
            
            # Par état
            etat = article['etat']
            etats[etat] = etats.get(etat, 0) + 1
            
            # Longueur
            longueurs.append(len(article['contenu']))
        
        analysis = {
            'topic': topic,
            'num_articles': len(results),
            'sections': sections,
            'etats': etats,
            'longueur_moyenne': np.mean(longueurs) if longueurs else 0,
            'articles': results
        }
        
        return analysis
    
    def display_analysis(self, analysis):
        """Affiche l'analyse d'un sujet"""
        
        if analysis is None:
            print("❌ Aucune analyse disponible")
            return
        
        print(f"\n{'='*70}")
        print(f"📊 ANALYSE DU SUJET : {analysis['topic']}")
        print('='*70)
        
        print(f"\n📚 {analysis['num_articles']} articles pertinents trouvés")
        
        print(f"\n📂 Répartition par section :")
        for section, count in sorted(analysis['sections'].items(), key=lambda x: x[1], reverse=True):
            print(f"   {count:3d} articles → {section[:60]}")
        
        print(f"\n⚖️  Répartition par état :")
        for etat, count in analysis['etats'].items():
            print(f"   {count:3d} articles → {etat}")
        
        print(f"\n📝 Longueur moyenne des articles : {analysis['longueur_moyenne']:.0f} caractères")
        
        print(f"\n{'─'*70}")
        print("🔝 Top 5 articles les plus pertinents :")
        print('─'*70)
        
        for i, result in enumerate(analysis['articles'][:5], 1):
            article = result['article']
            print(f"\n{i}. Article {article['num']} (score: {result['score']:.3f})")
            if article['chemin_hierarchique']:
                print(f"   {' > '.join(article['chemin_hierarchique'][-2:])}")
            print(f"   {article['contenu'][:150]}...")


def interactive_mode(searcher):
    """Mode interactif de recherche"""
    
    print("\n" + "="*70)
    print("🔍 MODE INTERACTIF - RECHERCHE DANS LE CODE DU TRAVAIL")
    print("="*70)
    print("\nCommandes disponibles :")
    print("  - Tapez votre question pour rechercher")
    print("  - 'analyse [sujet]' : Analyse approfondie d'un sujet")
    print("  - 'similaires [num]' : Articles similaires (ex: similaires L1132-1)")
    print("  - 'full' : Afficher le contenu complet des résultats")
    print("  - 'quit' : Quitter")
    print()
    
    show_full = False
    
    while True:
        try:
            query = input("\n💬 Votre requête : ").strip()
            
            if not query:
                continue
            
            if query.lower() == 'quit':
                print("👋 Au revoir !")
                break
            
            elif query.lower() == 'full':
                show_full = not show_full
                print(f"{'✅' if show_full else '❌'} Affichage contenu complet : {show_full}")
                continue
            
            elif query.lower().startswith('analyse '):
                topic = query[8:].strip()
                print(f"\n🔍 Analyse du sujet : {topic}")
                analysis = searcher.analyze_topic(topic, k=20)
                searcher.display_analysis(analysis)
            
            elif query.lower().startswith('similaires '):
                article_num = query[11:].strip()
                print(f"\n🔍 Articles similaires à {article_num}")
                results = searcher.find_related_articles(article_num, k=5)
                searcher.display_results(results, show_full)
            
            else:
                # Recherche normale
                results = searcher.search(query, k=10)
                searcher.display_results(results, show_full)
        
        except KeyboardInterrupt:
            print("\n\n👋 Au revoir !")
            break
        except Exception as e:
            print(f"❌ Erreur : {e}")


def run_validation_tests(searcher):
    """Exécute une série de tests de validation"""
    
    print("\n" + "="*70)
    print("🧪 TESTS DE VALIDATION DU SYSTÈME")
    print("="*70)
    
    test_cases = [
        {
            'name': "Test 1 : Discrimination",
            'query': "Quels sont les droits du salarié en cas de discrimination au travail ?",
            'expected_articles': ["L1132-1", "L1132-2", "L1132-3"],
            'k': 10
        },
        {
            'name': "Test 2 : Effectifs",
            'query': "Comment calculer les effectifs de l'entreprise pour les obligations légales ?",
            'expected_articles': ["L1111-2", "L1111-3"],
            'k': 10
        },
        {
            'name': "Test 3 : Télétravail",
            'query': "télétravail conditions mise en place",
            'expected_articles': [],  # À définir selon votre connaissance
            'k': 10
        },
        {
            'name': "Test 4 : Harcèlement",
            'query': "harcèlement moral sanctions protection salarié",
            'expected_articles': [],
            'k': 10
        }
    ]
    
    total_tests = len(test_cases)
    passed_tests = 0
    
    for test in test_cases:
        print(f"\n{'─'*70}")
        print(f"🧪 {test['name']}")
        print(f"   Requête : {test['query']}")
        print('─'*70)
        
        results = searcher.search(test['query'], k=test['k'])
        
        print(f"\n   📊 {len(results)} résultats trouvés")
        
        if results:
            print(f"   🔝 Top 3 :")
            for i, result in enumerate(results[:3], 1):
                print(f"      {i}. Article {result['num']} (score: {result['score']:.3f})")
            
            # Vérifier si les articles attendus sont dans les résultats
            if test['expected_articles']:
                found_nums = [r['num'] for r in results]
                found_expected = [art for art in test['expected_articles'] if art in found_nums]
                
                if found_expected:
                    print(f"\n   ✅ Articles attendus trouvés : {', '.join(found_expected)}")
                    passed_tests += 1
                else:
                    print(f"\n   ⚠️  Articles attendus NON trouvés : {', '.join(test['expected_articles'])}")
            else:
                print(f"\n   ℹ️  Pas d'articles de référence pour ce test")
                passed_tests += 1
        else:
            print(f"\n   ❌ Aucun résultat")
    
    print(f"\n{'='*70}")
    print(f"📊 RÉSULTATS DES TESTS : {passed_tests}/{total_tests} réussis")
    print("="*70)


if __name__ == "__main__":
    # Configuration
    # MODEL_PATH = "../paraphrase-multilingual-MiniLM-L12-v2"  
    MODEL_PATH = "../OrdalieTech/Solon-embeddings-base-0.1"
    VECTORIZED_DIR = "./code_travail_vectorized"
    
    # Initialiser le système
    searcher = CodeDuTravailSearch(MODEL_PATH, VECTORIZED_DIR)
    
    # Menu principal
    print("\n" + "="*70)
    print("🇫🇷 SYSTÈME DE RECHERCHE - CODE DU TRAVAIL")
    print("="*70)
    print("\nQue voulez-vous faire ?")
    print("  1. Mode interactif (recherche libre)")
    print("  2. Tests de validation")
    print("  3. Les deux")
    
    choice = input("\nVotre choix (1/2/3) : ").strip()
    
    if choice == "1":
        interactive_mode(searcher)
    elif choice == "2":
        run_validation_tests(searcher)
    elif choice == "3":
        run_validation_tests(searcher)
        interactive_mode(searcher)
    else:
        print("❌ Choix invalide")
