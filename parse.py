"""
Script pour parser et vectoriser le Code du travail
Étapes : 
1. Parser le XML
2. Extraire et structurer les articles
3. Générer les embeddings
4. Stocker dans une base vectorielle FAISS
5. Tester la recherche sémantique
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import json
from pathlib import Path
import numpy as np

# Installation des dépendances nécessaires (à exécuter une fois)
"""
pip install sentence-transformers faiss-cpu pandas tqdm --break-system-packages
"""

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    import pandas as pd
    from tqdm import tqdm
except ImportError:
    print("⚠️  Modules manquants. Installez-les avec :")
    print("pip install sentence-transformers faiss-cpu pandas tqdm --break-system-packages")
    exit(1)


@dataclass
class Article:
    """Structure d'un article du code"""
    id: str
    num: str
    contenu: str
    etat: str
    date_modification: str
    titre_modification: Optional[str]
    
    # Métadonnées hiérarchiques
    chemin_hierarchique: List[str]  # Ex: ["Partie législative", "Livre Ier", ...]
    niveau_profondeur: int
    
    # Liens vers autres articles
    references: List[str]  # IDs des articles référencés
    
    # Métadonnées supplémentaires
    metadata: Dict


class CodeDuTravailParser:
    """Parser pour le Code du travail au format XML Légifrance"""
    
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.articles: List[Article] = []
        self.tree = None
        
    def parse(self) -> List[Article]:
        """Parse le fichier XML et extrait tous les articles"""
        # print(f"Lecture du fichier {self.xml_path}...")
        # self.tree = ET.parse(self.xml_path)
        # root = self.tree.getroot()

        try:
            print(f"\n📖 Lecture du fichier : {self.xml_path}")
            self.tree = ET.parse(self.xml_path)
            root = self.tree.getroot()
            print(f"✅ Fichier chargé avec succès")
            
        except FileNotFoundError:
            print(f"❌ ERREUR : Fichier introuvable : {self.xml_path}")
            return
        except ET.ParseError as e:
            print(f"❌ ERREUR de parsing XML : {e}")
            return

        print("Extraction des articles...")
        self._extract_articles(root, chemin=[])
        
        print(f"✅ {len(self.articles)} articles extraits")
        return self.articles
    
    def _extract_articles(self, element: ET.Element, chemin: List[str], niveau: int = 0):
        """Extraction récursive des articles avec leur contexte hiérarchique"""
        print(f"Exploration : <{element.tag}> (niveau {niveau}) - Chemin actuel : {' > '.join(chemin)}")
        # Si c'est un titre/section (balise <t>), on l'ajoute au chemin
        if element.tag == 'code':
            # Balise racine, on ne l'ajoute pas au chemin
            for child in element:
                self._extract_articles(child, chemin, niveau + 1)
        elif element.tag == 't':
            titre = element.get('title', '').strip()
            if titre:
                chemin = chemin + [titre]
            
            # Continuer la récursion dans les enfants
            for child in element:
                self._extract_articles(child, chemin, niveau + 1)
        
        # Si c'est un article, on l'extrait
        elif element.tag == 'article':
            article = self._parse_article(element, chemin, niveau)
            if article:
                self.articles.append(article)
    
    def _parse_article(self, element: ET.Element, chemin: List[str], niveau: int) -> Optional[Article]:
        """Parse un élément <article> individuel"""
        
        # Extraction des attributs
        article_id = element.get('id')
        num = element.get('num', '')
        etat = element.get('etat', '')
        date_mod = element.get('date', '')
        titre_mod = element.get('modTitle', '')
        
        # Extraction du contenu textuel (toutes les balises <p>)
        paragraphes = []
        for p in element.findall('.//p'):
            # Récupérer le texte en gérant les balises <a> (liens)
            texte = self._extract_text_with_links(p)
            if texte:
                paragraphes.append(texte)
        
        contenu = '\n\n'.join(paragraphes)
        
        if not contenu:
            return None
        
        # Extraction des références à d'autres articles
        references = self._extract_references(element)
        
        # Création de l'objet Article
        return Article(
            id=article_id,
            num=num,
            contenu=contenu,
            etat=etat,
            date_modification=date_mod,
            titre_modification=titre_mod,
            chemin_hierarchique=chemin.copy(),
            niveau_profondeur=niveau,
            references=references,
            metadata={
                'cid': element.get('cid', ''),
                'intOrdre': element.get('intOrdre', ''),
                'modId': element.get('modId', '')
            }
        )
    
    def _extract_text_with_links(self, element: ET.Element) -> str:
        """Extrait le texte d'un élément en préservant les références"""
        text_parts = []
        
        if element.text:
            text_parts.append(element.text)
        
        for child in element:
            if child.tag == 'a':
                # Pour les liens, on garde le texte et on note la référence
                link_text = child.text or ''
                text_parts.append(link_text)
            
            if child.tail:
                text_parts.append(child.tail)
        
        return ''.join(text_parts).strip()
    
    def _extract_references(self, element: ET.Element) -> List[str]:
        """Extrait les IDs des articles référencés dans les liens"""
        references = []
        
        for link in element.findall('.//a'):
            dest_id = link.get('destinationid')
            if dest_id:
                references.append(dest_id)
        
        return references
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convertit les articles en DataFrame pandas"""
        data = []
        for article in self.articles:
            row = {
                'id': article.id,
                'num': article.num,
                'contenu': article.contenu,
                'etat': article.etat,
                'date_modification': article.date_modification,
                'chemin': ' > '.join(article.chemin_hierarchique),
                'niveau': article.niveau_profondeur,
                'nb_references': len(article.references),
                'longueur': len(article.contenu)
            }
            data.append(row)
        
        return pd.DataFrame(data)
    
    def save_to_json(self, output_path: str):
        """Sauvegarde les articles structurés en JSON"""
        data = [asdict(article) for article in self.articles]
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"Articles sauvegardés dans {output_path}")

def vectorize_with_local_model(articles_json_path: str, model_path: str):
    """
    Vectorise les articles avec un modèle local
    
    Args:
        articles_json_path: Chemin vers articles_structures.json
        model_path: Chemin vers le dossier du modèle cloné
    """
    
    print("="*70)
    print("🔢 VECTORISATION AVEC MODÈLE LOCAL")
    print("="*70)
    
    # Charger les articles
    print(f"\n📖 Chargement des articles depuis {articles_json_path}...")
    with open(articles_json_path, 'r', encoding='utf-8') as f:
        articles_data = json.load(f)
    
    print(f"✅ {len(articles_data)} articles chargés")
    
    # Charger le modèle local
    print(f"\n🤖 Chargement du modèle local : {model_path}")
    
    try:
        model = SentenceTransformer(model_path)
        print(f"✅ Modèle local chargé avec succès")
    except Exception as e:
        print(f"❌ Erreur de chargement : {e}")
        print(f"\n💡 Vérifiez que le modèle a été cloné correctement :")
        print(f"   git clone https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        return None
    
    # Préparer les textes
    print(f"\n📝 Préparation des textes...")
    texts = []
    for article in articles_data:
        chemin_str = ' > '.join(article['chemin_hierarchique'])
        texte_complet = f"Article {article['num']}\n{chemin_str}\n\n{article['contenu']}"
        texts.append(texte_complet)
    
    print(f"   {len(texts)} textes préparés")
    
    # Vectorisation
    print(f"\n🔢 Génération des embeddings...")
    print(f"   (Cela peut prendre 5-15 minutes pour {len(texts)} articles)")
    
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    
    print(f"✅ Embeddings générés : {embeddings.shape}")
    
    # Créer l'index FAISS
    print(f"\n🏗️  Construction de l'index FAISS...")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    
    print(f"✅ Index créé avec {index.ntotal} vecteurs")
    
    # Sauvegarder
    output_dir = Path("./code_travail_vectorized")
    output_dir.mkdir(exist_ok=True)
    
    print(f"\n💾 Sauvegarde des fichiers...")
    
    faiss.write_index(index, str(output_dir / "faiss_index.bin"))
    
    with open(output_dir / "articles_metadata.json", 'w', encoding='utf-8') as f:
        json.dump(articles_data, f, ensure_ascii=False, indent=2)
    
    np.save(output_dir / "embeddings.npy", embeddings)
    
    config = {
        'model_path': model_path,
        'num_articles': len(articles_data),
        'embedding_dimension': dimension,
        'index_type': 'IndexFlatIP'
    }
    with open(output_dir / "config.json", 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    
    print(f"✅ Tous les fichiers sauvegardés dans : {output_dir}")
    
    return model, index, articles_data, embeddings


def test_search(model, index, articles_data, queries):
    """Test de recherche sémantique"""
    
    print(f"\n{'='*70}")
    print("🔍 TESTS DE RECHERCHE SÉMANTIQUE")
    print("="*70)
    
    for query in queries:
        print(f"\n{'─'*70}")
        print(f"🔎 Requête : \"{query}\"")
        print('─'*70)
        
        query_embedding = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        
        k = 5
        distances, indices = index.search(query_embedding, k)
        
        print(f"\nTop {k} résultats :")
        for i, (idx, score) in enumerate(zip(indices[0], distances[0]), 1):
            article = articles_data[idx]
            print(f"\n{i}. Article {article['num']} (score: {score:.3f})")
            
            # Afficher chemin court
            if len(article['chemin_hierarchique']) >= 2:
                chemin = ' > '.join(article['chemin_hierarchique'][-2:])
            else:
                chemin = ' > '.join(article['chemin_hierarchique'])
            print(f"   📂 {chemin}")
            
            # Afficher extrait
            contenu_preview = article['contenu'][:200].replace('\n', ' ')
            print(f"   📝 {contenu_preview}...")



def main():
    """Pipeline complet de traitement"""
    
    # Configuration
    XML_PATH = "Code_du_travail.xml" # Chemin vers le fichier XML du code du travail
    OUTPUT_DIR = Path("code_travail/") 
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print("=" * 70)
    print("🇫🇷  PIPELINE DE TRAITEMENT DU CODE DU TRAVAIL")
    print("=" * 70)
    
    # Étape 1 : Parsing
    print("\nÉTAPE 1 : PARSING DU XML")
    parser = CodeDuTravailParser(XML_PATH)
    articles = parser.parse()
    
    # Sauvegarder en JSON
    parser.save_to_json(OUTPUT_DIR / "articles_structures.json")
    
    # Créer un DataFrame pour analyse
    df = parser.to_dataframe()
    print("\n📊 Statistiques :")
    print(f"   - Nombre d'articles : {len(df)}")
    print(f"   - Longueur moyenne : {df['longueur'].mean():.0f} caractères")
    print(f"   - Articles avec références : {(df['nb_references'] > 0).sum()}")
    
    # Étape 2 : Vectorisation
    print("\n\n🔢 ÉTAPE 2 : VECTORISATION")
    # Configuration
    ARTICLES_JSON = "./code_travail/articles_structures.json"
    
    # OPTION 1 : Modèle cloné localement
    LOCAL_MODEL_PATH = "../paraphrase-multilingual-MiniLM-L12-v2"
    
    # OPTION 2 : Ou spécifier un autre chemin
    # LOCAL_MODEL_PATH = "C:/Users/franc/Documents/models/paraphrase-multilingual-MiniLM-L12-v2"
    
    # Vérifications
    if not Path(ARTICLES_JSON).exists():
        print(f"❌ Fichier introuvable : {ARTICLES_JSON}")
        print(f"💡 Exécutez d'abord : python parse_code_fixed.py")
        exit(1)
    
    if not Path(LOCAL_MODEL_PATH).exists():
        print(f"❌ Modèle introuvable : {LOCAL_MODEL_PATH}")
        print(f"\n💡 Clonez d'abord le modèle :")
        print(f"   git clone https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        print(f"\nOu utilisez vectorize_simple.py qui télécharge automatiquement un modèle public")
        exit(1)
    
    # Vectorisation
    print(f"📂 Utilisation du modèle local : {LOCAL_MODEL_PATH}\n")
    result = vectorize_with_local_model(ARTICLES_JSON, LOCAL_MODEL_PATH)
    
    if result is None:
        exit(1)
    
    model, index, articles_data, embeddings = result
    
    # Étape 3 : Tests de recherche
    print("\n\n🔍 ÉTAPE 3 : TESTS DE RECHERCHE SÉMANTIQUE")
    # Tests
    test_queries = [
        "Quels sont les droits du salarié en cas de discrimination ?",
        "Comment calculer les effectifs de l'entreprise ?",
        "Règles sur le télétravail",
        "Durée légale du travail et heures supplémentaires",
        "Harcèlement moral au travail"
    ]
    
    test_search(model, index, articles_data, test_queries)
    
    
    print(f"\n{'='*70}")
    print("🎉 SUCCÈS - Le système est opérationnel !")
    print("="*70)
    print(f"\n📊 Statistiques :")
    print(f"   - Articles indexés : {len(articles_data)}")
    print(f"   - Dimension des embeddings : {embeddings.shape[1]}")
    print(f"   - Taille de l'index : {index.ntotal} vecteurs")
    print(f"\n💡 Vous pouvez maintenant :")
    print(f"   - Faire des recherches sémantiques sur tout le code")
    print(f"   - Analyser les relations entre articles")
    print(f"   - Détecter des incohérences")


    return


if __name__ == "__main__":
    main()
