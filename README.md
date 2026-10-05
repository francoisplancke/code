# Recherche juridique France + Union européenne

Application locale de recherche juridique construite autour de **PostgreSQL**. Le corpus français LEGI est recherché en hybride (pgvector + lexical PostgreSQL) ; le corpus de l'Union européenne est recherché en plein texte PostgreSQL à partir du dump officiel EUR-Lex/Formex. L'interface Flask permet de basculer entre **France** et **Union européenne** depuis toutes les pages.

PostgreSQL est la source de vérité. Les archives sources, artefacts intermédiaires, caches SPARQL et embeddings sont reproductibles et ne sont pas versionnés.

## Architecture

Le système sépare explicitement **sources canoniques**, **stockage**, **recherche** et **analyse**. Les LLM et services d'enrichissement ne font jamais partie de la chaîne de vérité documentaire.

```text
Sources canoniques                    Ingestion déterministe
DILA / LEGI (.tar.gz) ─────────────► parse_legi_postgres.py ───┐
                                                               │
EUR-Lex FMX + CELLAR ───────────────► build.py eu ─────────────┤
  ├─ identité CELEX/CELLAR                                      │
  ├─ arbre des dispositions                                     ▼
  └─ normalisation juridique                            PostgreSQL = vérité
                                                        documentaire
Sources externes optionnelles                                  │
CELLAR NIM ── build.py nim ──► artefacts transposition         ├─ corpus FR
JEV ──► enrichissement futur/non bloquant                      └─ corpus UE
                                                               │
                          ┌────────────────────────────────────┤
                          ▼                                    ▼
                  Recherche hybride FR                 Recherche lexicale UE
                  pgvector + PostgreSQL                PostgreSQL / GIN
                          └───────────────┬────────────────────┘
                                          ▼
                                      Flask / UI
                                    France ↔ UE
                                          │
                                          ▼
                                Couche d'analyse R7.4+
                          obligations / comparaison / coûts
                                          │
                          abstraction LLM configurable
                    ┌──────────┬──────────┼───────────┐
                  local      OpenAI    DeepSeek     Gemini
                 défaut      fallback   fallback     fallback
```

**PostgreSQL est la source de vérité**. Les tables principales France sont `corpus`, `texte`, `unite`, `version`, `relation_juridique`, `embedding_model`, `version_embedding`. Les tables UE sont `eu_act` et `eu_provision`; `eu_provision.search_vector` est généré et indexé en GIN. Les index, embeddings, caches SPARQL et artefacts sont dérivés et reproductibles.

La couche `legal/llm/` est volontairement indépendante du build. `local` est le provider par défaut et vise un endpoint compatible avec l'API OpenAI; `openai`, `deepseek` et `gemini` sont des fallbacks configurables. Aucune clé LLM n'est nécessaire pour `build.py legi`, `build.py eu` ou `build.py nim`.

JEV n'est pas une source canonique et n'est actuellement appelé par aucun pipeline. Sa configuration est réservée à un éventuel enrichissement externe futur : une indisponibilité de JEV ne doit jamais empêcher la reconstruction ou la consultation des corpus.

## Prérequis

- Python 3.11+ ;
- PostgreSQL avec l'extension `vector` pour la recherche sémantique française ;
- espace disque suffisant pour les archives et les artefacts de build ;
- accès Internet pendant le build UE pour résoudre les identités CELLAR via le endpoint SPARQL public ;
- GPU CUDA facultatif mais recommandé pour vectoriser LEGI.

Exemple PostgreSQL :

```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createdb legal
sudo -u postgres psql -d legal -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

Installation Python :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pour les tests :

```bash
pip install -r requirements-dev.txt
make test
```

## Récupérer les données sources

### France — DILA / LEGI

Le stock LEGI est publié par la DILA dans le répertoire Open Data :

`https://echanges.dila.gouv.fr/OPENDATA/LEGI/`

Télécharger un dump global `Freemium_legi_global_YYYYMMDD-HHMMSS.tar.gz`. Il n'est pas nécessaire de le décompresser : l'importeur lit directement l'archive en streaming.

Exemple :

```bash
wget https://echanges.dila.gouv.fr/OPENDATA/LEGI/Freemium_legi_global_YYYYMMDD-HHMMSS.tar.gz
```

### Union européenne — EUR-Lex Data Dump

Pour le corpus UE complet, utiliser le **Data Dump officiel EUR-Lex**. Le service permet de télécharger en masse les actes juridiques en vigueur du **secteur CELEX 3**, par langue, et nécessite un compte EU Login. Dans Data Dump, créer une demande **Legislation in force**, choisir la langue **FR** et le format **FMX (Formex)**, puis télécharger l'archive `LEG_FR_FMX_...zip`.

Documentation officielle :

- `https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html`
- Data Dump : `https://datadump.publications.europa.eu/`

EUR-Lex recommande Data Dump ou l'accès direct CELLAR pour les grands volumes. Le build utilise ensuite le endpoint SPARQL public CELLAR pour rattacher les UUID CELLAR aux CELEX ; les réponses sont mises en cache sous `artifacts/eu/cache/` afin que le traitement soit reprenable.

Le corpus validé pendant le développement était le dump français FMX `LEG_FR_FMX_20260927_01_00.zip`. Les nombres exacts dépendent du snapshot téléchargé.

## Configuration

Copier le modèle puis adapter les chemins et informations d'exploitation :

```bash
cp .env.example .env
set -a
source .env
set +a
```

Variables principales :

| Variable | Rôle | Défaut / exemple |
|---|---|---|
| `LEGAL_DSN` | connexion PostgreSQL | `postgresql://postgres:postgres@localhost:5432/legal` |
| `LEGAL_LEGI_ARCHIVE` | archive source LEGI | `/data/Freemium_legi_global_....tar.gz` |
| `LEGAL_EU_FMX_ZIP` | dump FMX français EUR-Lex | `/data/LEG_FR_FMX_....zip` |
| `LEGAL_MODEL` | modèle SentenceTransformer France | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `LEGAL_DEVICE` | calcul embeddings | `cuda` ou `cpu` |
| `LEGAL_ETAT` | versions françaises recherchées | `VIGUEUR` |
| `LEGAL_SEARCH_K` | résultats par défaut | `10` |
| `LEGAL_LEXICAL_WEIGHT` | poids lexical recherche FR | `0.25` |
| `LEGAL_QUERY_LOG_RETENTION_DAYS` | rétention journal des requêtes | `30` |
| `LEGAL_OPERATOR_NAME` | mentions légales | à renseigner |
| `LEGAL_PRIVACY_CONTACT` | contact confidentialité | à renseigner |
| `LEGAL_EU_DATA_DATE` | date du snapshot UE affichée | à renseigner |

Voir `.env.example` pour la liste complète.

### LLM et services externes optionnels

Le provider d'analyse se sélectionne avec `LEGAL_LLM_PROVIDER=local|openai|deepseek|gemini`. `LEGAL_LLM_MODEL`, `LEGAL_LLM_BASE_URL` et `LEGAL_LLM_TIMEOUT` permettent de surcharger le modèle, l'endpoint et le délai. Pour un endpoint local protégé, utiliser `LEGAL_LLM_API_KEY`.

Les providers cloud exigent uniquement leur propre secret : `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` ou `GEMINI_API_KEY`. Ces secrets doivent rester dans `.env` ou le gestionnaire de secrets de déploiement et ne doivent jamais être commités. Ils ne sont pas requis pour construire les bases.

`JEV_API_KEY` et `JEV_BASE_URL` sont réservés à JEV. **Le code actuel ne consomme pas JEV** : ces variables documentent l'architecture cible d'enrichissement optionnel et ne sont requises par aucune commande de build ou d'exploitation actuelle.


## Construire la base

### Tout construire

Après avoir défini `LEGAL_LEGI_ARCHIVE`, `LEGAL_EU_FMX_ZIP` et `LEGAL_DSN` :

```bash
python build.py all
```

ou :

```bash
make build
```

### France uniquement

```bash
python build.py legi
# ou
python build.py legi /data/Freemium_legi_global_....tar.gz
```

L'import crée le schéma LEGI, charge les textes puis vectorise les versions utiles. Pour importer sans vectorisation :

```bash
python build.py legi --no-vectorize
```

### Union européenne uniquement

```bash
python build.py eu
# ou
python build.py eu /data/LEG_FR_FMX_....zip
```

Le pipeline UE est idempotent côté PostgreSQL et exécute : inventaire FMX → identité offline → résolution CELLAR → normalisation CELEX → identité canonique → extraction des dispositions → normalisation des corrigenda → migration/import PostgreSQL.

Les artefacts et audits sont écrits dans `artifacts/eu/` et ignorés par Git. Ils permettent de reprendre les appels CELLAR et d'auditer les lignes rejetées ou les parents synthétiques.

Sur le snapshot de validation `20260927`, l'import final conservait **121 019 dispositions**, dont **125 nœuds structurels à texte vide**, sans perte de disposition valide. La table `eu_act` contenait 29 974 identités canoniques plus un parent synthétique explicitement audité.

### Mesures nationales de transposition françaises (optionnel)

La préparation du futur moteur de surtransposition conserve un enrichissement NIM officiel CELLAR, mais il n'est pas requis pour faire fonctionner l'interface actuelle :

```bash
python build.py nim
```

Cette commande doit être lancée après `build.py eu`. Elle découvre les mesures nationales françaises et enrichit leurs métadonnées dans `artifacts/eu/nim/`. Elle ne modifie pas encore le schéma applicatif PostgreSQL.

## Lancer l'application

```bash
python app.py
# ou
make run
```

Par défaut : `http://127.0.0.1:5000/`.

- **France** est le corpus sélectionné au premier affichage ;
- **Union européenne** utilise directement `eu_act` / `eu_provision` dans le même PostgreSQL ;
- `/eu/texte/<CELEX>` affiche les dispositions d'un acte ;
- le bouton de matching propose des résultats LEGI sans enregistrer automatiquement de relation juridique.

La recherche française utilise pgvector + un signal lexical PostgreSQL. Le score est un score de classement, pas une probabilité de validité juridique.

## Tests et vérifications avant commit

```bash
make test
python -m py_compile app.py build.py parse_legi_postgres.py search_interactive.py
```

Vérifier également manuellement : `/`, `/article/...`, `/texte/...`, `/mentions`, `/eu`, `/eu/texte/<CELEX>` et `/eu/texte/<CELEX>/matching`.

## Données non versionnées

`.gitignore` exclut les archives DILA/EUR-Lex, `artifacts/`, caches CELLAR, bases SQLite historiques, embeddings/index locaux, logs, environnements virtuels et secrets `.env`.

Le dépôt doit donc contenir le **code permettant de reconstruire la base**, jamais les dizaines de gigaoctets de données sources ou dérivées.

## Provenance et prudence juridique

Les données françaises proviennent de la DILA/Légifrance. Les données européennes proviennent d'EUR-Lex/CELLAR, gérés par l'Office des publications de l'Union européenne. CELLAR est le dépôt de contenu et de métadonnées utilisé par EUR-Lex ; les documents peuvent notamment être récupérés en Formex et les métadonnées interrogées via SPARQL.

L'application est un outil de recherche documentaire. Les résultats algorithmiques peuvent être incomplets ou mal classés et doivent être vérifiés dans les sources officielles avant toute décision juridique.
