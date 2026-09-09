# Recherche sémantique dans le corpus législatif consolidé LEGI

Ce projet importe le corpus législatif consolidé **LEGI** de la DILA
dans PostgreSQL, vectorise les versions actuellement en vigueur avec
SentenceTransformers + pgvector, puis permet de les interroger soit en
ligne de commande, soit depuis une application web Flask.

PostgreSQL constitue la **source de vérité**. Les embeddings pgvector
sont une représentation dérivée du corpus juridique. L'architecture est
prévue pour accueillir ultérieurement d'autres corpus (JORF, KALI,
EUR-Lex, jurisprudence, etc.) et un graphe Apache AGE.

## Vue d'ensemble

``` text
Archive LEGI .tar.gz
        |
        | lecture streaming r|gz
        v
parse_legi_postgres.py
        |
        v
PostgreSQL
├── corpus
├── texte
├── unite
├── version
├── relation_juridique
└── import_log
        |
        | ETAT = VIGUEUR
        v
SentenceTransformer
        |
        v
pgvector
├── embedding_model
└── version_embedding
        |
        v
Index HNSW cosine
        |
        +----------------------+
        |                      |
        v                      v
search_interactive.py        app.py
CLI hybride                 interface web
```

La recherche actuelle porte sur **654 939 versions `VIGUEUR`
vectorisées** avec le modèle :

``` text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Dimension des embeddings : **384**.

------------------------------------------------------------------------

## 1. Prérequis

Le projet est actuellement utilisé sous **WSL 2 / Ubuntu**.

## Dépendances Python

Le projet utilise les bibliothèques Python suivantes :

| Bibliothèque | Utilisation |
|---|---|
| `psycopg[binary]` | Connexion à PostgreSQL |
| `pgvector` | Support des vecteurs PostgreSQL / pgvector |
| `sentence-transformers` | Génération des embeddings |
| `torch` | Exécution du modèle, notamment sur GPU CUDA |
| `numpy` | Manipulation des vecteurs |
| `tqdm` | Barres de progression lors des imports/vectorisations |
| `flask` | Application web |

### PostgreSQL

``` bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo service postgresql start
```

Créer la base :

``` bash
sudo -u postgres psql
```

Puis :

``` sql
ALTER USER postgres WITH PASSWORD 'postgres';
CREATE DATABASE legal;
\q
```

Tester :

``` bash
psql -h localhost -U postgres -d legal
```

Les exemples utilisent :

``` text
postgresql://postgres:postgres@localhost:5432/legal
```

Utiliser un autre mot de passe hors environnement local.

### Environnement Python

``` bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install "psycopg[binary]" tqdm
```

### pgvector

Vérifier la version PostgreSQL :

``` bash
psql --version
apt-cache search pgvector
```

Exemple pour PostgreSQL 16 :

``` bash
sudo apt install postgresql-16-pgvector
sudo -u postgres psql -d legal -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Installer les dépendances Python utilisées pour les embeddings et la
recherche :

``` bash
python3 -m pip install pgvector sentence-transformers numpy
```

Pour l'application web, installer également Flask :

``` bash
python3 -m pip install flask
```

------------------------------------------------------------------------

## 2. Télécharger les données LEGI

Le corpus officiel est publié par la DILA :

``` text
https://echanges.dila.gouv.fr/OPENDATA/LEGI/
```

Le dump global utilisé pour les résultats documentés ici est :

``` text
Freemium_legi_global_20250713-140000.tar.gz
```

Téléchargement avec `wget` :

``` bash
wget https://echanges.dila.gouv.fr/OPENDATA/LEGI/Freemium_legi_global_20250713-140000.tar.gz
```

ou avec `curl` :

``` bash
curl -L -O https://echanges.dila.gouv.fr/OPENDATA/LEGI/Freemium_legi_global_20250713-140000.tar.gz
```

Vérifier :

``` bash
ls -lh Freemium_legi_global_20250713-140000.tar.gz
```

### Ne pas décompresser l'archive

L'archive contient plusieurs millions de petits fichiers XML. Le parseur
la lit directement en streaming :

``` python
tarfile.open(path, mode="r|gz")
```

Il n'est donc pas nécessaire d'extraire les XML sur le disque.

### Mises à jour incrémentales

Le répertoire DILA contient également des archives quotidiennes :

``` text
LEGI_YYYYMMDD-HHMMSS.tar.gz
```

Le dump global constitue actuellement le point de départ.
L'automatisation des incréments reste une évolution future.

------------------------------------------------------------------------

## 3. Modèle d'embeddings et GPU

Le modèle utilisé est :

``` text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Il produit des vecteurs de dimension **384**.

Tester le modèle sur CUDA :

``` bash
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer(
    'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    device='cuda'
)
print(m.device)
print(m.encode(['test embedding']).shape)
"
```

Résultat attendu :

``` text
cuda:0
(1, 384)
```

Vérifier uniquement PyTorch/CUDA :

``` bash
python3 -c "import torch; print('CUDA:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU uniquement')"
```

### Utilisation hors ligne

Après le premier téléchargement, le modèle est conservé dans le cache
Hugging Face local.

Pour interdire les accès au Hub :

``` bash
export HF_HUB_OFFLINE=1
```

Le message :

``` text
Warning: You are sending unauthenticated requests to the HF Hub
```

ne signifie pas que le corpus ou les embeddings sont distants. Il
indique seulement que SentenceTransformers/Hugging Face peut contacter
le Hub pour résoudre ou vérifier les fichiers du modèle.

Avec `HF_HUB_OFFLINE=1`, la chaîne peut fonctionner entièrement en local
:

``` text
Corpus LEGI       local
PostgreSQL        local
pgvector          local
index HNSW        local
MiniLM            cache local
CUDA / GPU        local
```

------------------------------------------------------------------------

## 4. Construire la base depuis zéro

Le script principal est :

``` text
parse_legi_postgres.py
```

Il :

-   lit directement le `.tar.gz` en streaming ;
-   détecte les XML de type `ARTICLE` ;
-   importe les textes du corpus LEGI ;
-   exclut par défaut les versions `ABROGE` ;
-   construit `corpus -> texte -> unite -> version` ;
-   conserve les métadonnées juridiques ;
-   importe les relations entre textes et articles ;
-   calcule un `checksum_sha256` pour chaque version ;
-   peut vectoriser ensuite les seules versions `VIGUEUR`.

### Import + vectorisation

``` bash
python3 parse_legi_postgres.py \
  "Freemium_legi_global_20250713-140000.tar.gz" \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --embedding-model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --batch-size 16
```

### Import sans vectorisation

``` bash
python3 parse_legi_postgres.py \
  "Freemium_legi_global_20250713-140000.tar.gz" \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --no-vectorize
```

Le filtre appliqué au corpus source est actuellement :

``` text
ETAT != ABROGE
```

Les versions historiques `MODIFIE`, `PERIME`, `TRANSFERE`, etc. restent
dans PostgreSQL pour les analyses historiques et les futurs traitements
de graphe.

------------------------------------------------------------------------

## 5. Structure PostgreSQL

### `corpus`

Identifie la source juridique, actuellement `LEGI`.

### `texte`

Représente les textes juridiques : `CODE`, `LOI`, `DECRET`, `ARRETE`,
`ORDONNANCE`, etc.

Le titre n'est pas un identifiant unique. L'identifiant source
(`LEGITEXT...`, `JORFTEXT...`) est conservé.

### `unite`

Représente une unité documentaire logique, principalement un article.

Un numéro tel que `L1132-1` n'est **pas globalement unique** : plusieurs
textes peuvent contenir un article portant le même numéro.

Le chemin hiérarchique est stocké dans :

``` text
unite.chemin
```

et non dans `version`.

### `version`

Représente une version juridique d'une unité. Une même unité peut avoir
plusieurs versions historiques.

### `relation_juridique`

Conserve les relations LEGI : modification, citation, création,
abrogation, transfert, etc. Elles pourront servir à construire
ultérieurement un graphe Apache AGE.

### Tables pgvector

`embedding_model` décrit les modèles d'embeddings utilisés.

`version_embedding` associe un embedding à :

``` text
version_id
model_id
content_checksum
```

Cette structure permet plusieurs modèles et évite de recalculer un
embedding dont le contenu n'a pas changé.

------------------------------------------------------------------------

## 6. Vectoriser une base existante

Pour une base déjà importée, utiliser :

``` text
vectorize_existing_postgres.py
```

Commande :

``` bash
python3 vectorize_existing_postgres.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --batch-size 16
```

Seules les versions :

``` text
ETAT = VIGUEUR
```

sont actuellement vectorisées.

La vectorisation est **reprenable** : après une interruption ou un
redémarrage, relancer la même commande. Les embeddings déjà présents
avec le bon `content_checksum` ne sont pas recalculés.

------------------------------------------------------------------------

## 7. Vérifier la vectorisation

Nombre de versions `VIGUEUR` :

``` sql
SELECT COUNT(*)
FROM version
WHERE etat = 'VIGUEUR';
```

Résultat sur le dump documenté :

``` text
654939
```

Nombre d'embeddings :

``` sql
SELECT COUNT(*)
FROM version_embedding ve
JOIN embedding_model em ON em.id = ve.model_id
WHERE em.name = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2';
```

Résultat attendu :

``` text
654939
```

Vérifier qu'aucune version n'est manquante ou obsolète :

``` sql
SELECT COUNT(*) AS restant
FROM version v
LEFT JOIN embedding_model em
  ON em.name = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
LEFT JOIN version_embedding ve
  ON ve.version_id = v.id
 AND ve.model_id = em.id
WHERE v.etat = 'VIGUEUR'
  AND (
      ve.version_id IS NULL
      OR ve.content_checksum IS DISTINCT FROM v.checksum_sha256
  );
```

Résultat attendu :

``` text
0
```

Vérifier le modèle :

``` sql
SELECT id, name, dimension, normalize
FROM embedding_model;
```

Valeurs attendues pour MiniLM :

``` text
dimension = 384
normalize = true
```

### Vérifier l'index HNSW

``` sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'version_embedding';
```

Un index de la forme :

``` text
version_embedding_hnsw_384_...
```

doit utiliser :

``` text
USING hnsw
vector_cosine_ops
```

L'index est partiel par modèle afin de permettre plusieurs modèles et
dimensions.

------------------------------------------------------------------------

## 8. Recherche en ligne de commande

Le script :

``` text
search_interactive.py
```

interroge directement PostgreSQL + pgvector. FAISS, `embeddings.npy` et
`articles_metadata.json` ne sont plus utilisés.

``` text
Question
   |
   v
SentenceTransformer
   |
   | embedding 384D
   v
pgvector / HNSW
   |
   | candidats sémantiques
   v
Reranking lexical PostgreSQL
   |
   v
Résultats LEGI
```

### Recherche simple

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --query "Quelles sont les obligations de l'employeur concernant le harcèlement moral ?"
```

### Recherche hybride

Par défaut :

``` text
75 % vectoriel
25 % lexical
```

Le signal lexical exploite notamment le titre du texte, le numéro
d'article et son contenu.

Modifier le poids lexical :

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --lexical-weight 0.35 \
  --query "durée maximale quotidienne du travail"
```

Ici le classement utilise 65 % de signal vectoriel et 35 % de signal
lexical.

Le score hybride est un **score de classement**, pas une probabilité de
validité ou de pertinence juridique.

### Recherche vectorielle uniquement

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --vector-only \
  --query "harcèlement moral au travail"
```

### Nombre de résultats et seuil

Par défaut :

``` text
-k 10
```

Exemple :

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  -k 20 \
  --min-score 0.40 \
  --query "obligations de sécurité de l'employeur"
```

### Filtrer par type

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --type-texte CODE \
  --query "obligations de l'employeur concernant le harcèlement moral"
```

Types possibles selon le corpus : `CODE`, `LOI`, `DECRET`, `ARRETE`,
`ORDONNANCE`, etc.

### Filtrer sur un texte précis

Le filtre `--texte` utilise l'identifiant source du texte.

Exemple avec le Code du travail :

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda \
  --texte LEGITEXT000006072050 \
  --query "obligations de l'employeur concernant le harcèlement moral"
```

### Mode interactif

Sans `--query` :

``` bash
python3 search_interactive.py \
  --dsn "postgresql://postgres:postgres@localhost:5432/legal" \
  --model "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
  --device cuda
```

Le modèle reste chargé entre les recherches. C'est le mode recommandé
pour les tests manuels.

### Options principales

``` bash
python3 search_interactive.py --help
```

Principales options :

``` text
--dsn
--model
--device
--etat
--query
-k
--min-score
--texte
--type-texte
--full
--vector-only
--lexical-weight
```

------------------------------------------------------------------------

## 9. Application web Flask

`app.py` fournit une interface web au moteur PostgreSQL + pgvector. Elle
utilise la même base, le même modèle d'embeddings et la même logique de
recherche hybride que `search_interactive.py`.

L'application tient compte du fait que le corpus contient **plusieurs
codes et plusieurs types de textes**. Un numéro d'article n'est donc
jamais supposé unique à l'échelle du corpus.

### Dépendances

Avec l'environnement virtuel activé :

``` bash
python3 -m pip install flask "psycopg[binary]" pgvector sentence-transformers numpy
```

### Lancer l'application

Configuration minimale :

``` bash
export LEGAL_DSN="postgresql://postgres:postgres@localhost:5432/legal"
export LEGAL_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
export LEGAL_DEVICE="cuda"
```

Puis :

``` bash
python3 app.py
```

Si le modèle est déjà présent dans le cache local et que l'application
doit fonctionner sans accès Hugging Face :

``` bash
export HF_HUB_OFFLINE=1
python3 app.py
```

### Interface de recherche

La page principale permet d'effectuer une recherche dans les versions
actuellement indexées.

Les résultats affichent notamment :

-   le titre du texte (`Code du travail`, loi, décret, etc.) ;
-   le type du texte (`CODE`, `LOI`, `DECRET`, etc.) ;
-   le numéro de l'article ;
-   l'état de la version ;
-   la date de début ;
-   les identifiants source (`LEGIARTI`, `LEGITEXT`, `JORFTEXT`, etc.) ;
-   le chemin hiérarchique issu de `unite.chemin` ;
-   un extrait du contenu ;
-   le score de recherche.

Le chemin hiérarchique est présenté sous une forme lisible, par exemple
:

``` text
Partie
> Livre
> Titre
> Chapitre
```

et non sous la forme brute du JSON PostgreSQL.

### Filtres multi-corpus / multi-textes

L'application ne suppose plus qu'un article appartient au Code du
travail.

Les filtres permettent de distinguer les différents textes et types
présents dans PostgreSQL. L'identification d'un article repose sur son
unité et son texte parent, et pas uniquement sur son numéro.

Par exemple, `L1132-1` peut exister dans plusieurs codes.

### Pages de détail

L'application dispose de vues permettant de consulter un article et son
texte parent avec :

-   le titre réel du texte ;
-   son type ;
-   son identifiant source ;
-   le numéro de l'article ;
-   le chemin hiérarchique ;
-   le contenu de la version ;
-   les métadonnées disponibles.

Les templates concernés sont notamment :

``` text
templates/index.html
templates/article.html
templates/texte.html
```

### Source des données et avertissements

L'interface doit afficher clairement que :

-   les données proviennent de la DILA / Légifrance ;
-   le service est un moteur de recherche documentaire et non un conseil
    juridique ;
-   les résultats algorithmiques peuvent être incomplets ou mal classés
    ;
-   l'utilisateur doit vérifier le texte officiel avant toute décision
    juridique.

Une page dédiée aux mentions, à la confidentialité et aux sources peut
être exposée par l'application.

Les informations de source peuvent être configurées avec des variables
d'environnement, par exemple :

``` bash
export LEGAL_DATA_SOURCE_NAME="DILA / Légifrance — corpus consolidé LEGI"
export LEGAL_DATA_ARCHIVE="Freemium_legi_global_20250713-140000.tar.gz"
export LEGAL_DATA_DATE="2025-07-13"
```

Avant une mise à disposition publique, renseigner également les
informations propres à l'exploitant :

``` bash
export LEGAL_OPERATOR_NAME="Nom de l'exploitant"
export LEGAL_PRIVACY_CONTACT="contact@example.fr"
```

### Journalisation des recherches

L'application peut conserver dans PostgreSQL un journal minimal des
recherches :

``` text
requête
timestamp
adresse IP
```

La table correspondante est :

``` sql
CREATE TABLE IF NOT EXISTS search_query_log (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    query TEXT NOT NULL,
    ip_address INET
);
```

La durée de conservation est configurable, par exemple :

``` bash
export LEGAL_QUERY_LOG_RETENTION_DAYS=30
```

Les journaux arrivés à expiration doivent être purgés.

L'adresse IP et le contenu d'une requête pouvant constituer des données
personnelles, cette journalisation doit être documentée dans les
informations de confidentialité de l'application et rester limitée à la
finalité définie.

### Application derrière un reverse proxy

`request.remote_addr` correspond à l'adresse vue par Flask.

Si l'application est ensuite placée derrière Nginx, Traefik, Cloudflare
ou un autre reverse proxy, ne pas faire confiance directement à un
en-tête `X-Forwarded-For` envoyé par le client. La configuration des
proxys de confiance doit être faite explicitement avant d'utiliser
l'adresse transmise par le proxy.

### Exemple de démarrage complet

``` bash
source .venv/bin/activate

export LEGAL_DSN="postgresql://postgres:postgres@localhost:5432/legal"
export LEGAL_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
export LEGAL_DEVICE="cuda"
export HF_HUB_OFFLINE=1

export LEGAL_DATA_ARCHIVE="Freemium_legi_global_20250713-140000.tar.gz"
export LEGAL_DATA_DATE="2025-07-13"
export LEGAL_QUERY_LOG_RETENTION_DAYS=30

python3 app.py
```

------------------------------------------------------------------------

## 10. Résultats validés sur le dump global

Import documenté :

``` text
XML parcourus           : 2 557 045
XML ARTICLE             : 1 750 418
articles acceptés       : 1 386 918
articles ignorés        :   363 500
relations importées     : 6 743 301
erreurs de parsing      :         0
```

Après déduplication / UPSERT PostgreSQL :

``` text
corpus                   :         1
textes                   :   127 919
unités                   : 1 006 750
versions                 : 1 379 408
relations juridiques     : 6 715 537
```

Vectorisation :

``` text
versions VIGUEUR         : 654 939
embeddings calculés      : 654 939
embeddings restants      :       0
```

------------------------------------------------------------------------

## 11. État actuel de l'architecture

``` text
Corpus                   LEGI
Base principale          PostgreSQL
Recherche vectorielle    pgvector
Index                    HNSW / cosine
Modèle                   paraphrase-multilingual-MiniLM-L12-v2
Dimension                384
Versions vectorisées     VIGUEUR
Nombre vectorisé         654 939
Recherche                hybride vectorielle + lexicale
CLI                      search_interactive.py
Web                      app.py / Flask
```

Les versions historiques restent disponibles dans PostgreSQL mais ne
font pas encore partie de l'index sémantique principal.

------------------------------------------------------------------------

## 12. Évolutions prévues

-   ingestion automatique des mises à jour incrémentales LEGI ;
-   filtres supplémentaires par date et corpus ;
-   ajout d'Apache AGE ;
-   construction du graphe des relations juridiques ;
-   ajout d'autres corpus : JORF, KALI, EUR-Lex, jurisprudence ;
-   extraction d'obligations juridiques ;
-   agents spécialisés en cohérence, simplification et analyse
    réglementaire.
