Structure du Projet
Le projet est articulé autour de deux scripts principaux :
    parse.py : Le moteur de données. Il gère l'extraction, la structuration et la vectorisation (embedding) du corpus législatif.
    search_interactive.py : L'interface utilisateur. Il permet d'interroger la base de données vectorielle, de trouver des articles similaires et d'effectuer des analyses thématiques.
    code_travail_vectorized/ : Dossier (généré) contenant l'index FAISS, les métadonnées JSON et les vecteurs NumPy.

Étapes d'Implémentation
1. Parsing et Structuration (ETL)
Le script traite les fichiers XML sources (format Légifrance).
Hiérarchie : Contrairement à un simple texte plat, le script reconstruit le chemin hiérarchique (Partie > Livre > Titre) pour chaque article.
Nettoyage : Extraction du texte brut des balises <p> et gestion des liens hypertextes internes.
Références : Extraction des IDs des articles cités pour permettre une future analyse de graphe.

2. Vectorisation Sémantique
Pour transformer le texte juridique en vecteurs mathématiques, nous utilisons :
Modèle : paraphrase-multilingual-MiniLM-L12-v2. Ce modèle est optimisé pour comprendre le sens des phrases dans plusieurs langues, dont le français.
Contexte : Chaque article est vectorisé avec son numéro et son chemin hiérarchique pour enrichir la recherche.

3. Indexation et Stockage
FAISS (Facebook AI Similarity Search) : Utilisation d'un index de type IndexFlatIP pour des recherches de similarité cosinus extrêmement rapides, même sur des milliers d'articles.
Métadonnées : Stockage séparé des contenus et métadonnées en JSON pour un accès rapide lors de l'affichage des résultats.

🚀 Utilisation
Prérequis
    pip install sentence-transformers faiss-cpu pandas tqdm

Étape 1 : Préparer les données
    Placez votre fichier Code_du_travail.xml à la racine et lancez le pipeline de traitement :
    python parse.py
    Cette commande va générer les fichiers nécessaires dans ./code_travail_vectorized/.

Étape 2 : Mode Recherche et Analyse
    Lancez l'interface interactive :
    python search_interactive.py

Commandes disponibles dans le mode interactif :
    Recherche simple : Tapez simplement votre question (ex: "Conditions de mise en place du télétravail").
    analyse [sujet] : Génère des statistiques sur la répartition des articles par section pour un thème donné.
    similaires [num_article] : Trouve les articles juridiquement proches d'un article spécifique (ex: similaires L1132-1).
    full : Alterne entre l'affichage d'un résumé ou du contenu complet des articles.
    quit : Quitter l'application.

Installation:
    Installation des librairies
    pip install sentence-transformers faiss-cpu numpy
    pip install flask

    Ajout du modèle au niveau du répertoire supérieur
    git clone https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
