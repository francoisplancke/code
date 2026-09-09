"""
Importeur LEGI -> PostgreSQL (V3)

Objectif
--------
- lire directement un stock LEGI décompressé OU une archive .tar.gz/.tgz ;
- ne jamais extraire les millions de petits XML lorsque l'entrée est une archive ;
- normaliser les données en : corpus -> texte -> unite -> version ;
- conserver les relations juridiques LEGI pour une future projection Apache AGE ;
- exclure par défaut les versions dont ETAT = ABROGE.

PostgreSQL est la source de vérité. Les embeddings pgvector peuvent être calculés
à la fin de l'import ; le graphe AGE restera une représentation dérivée.

Dépendances minimales :
    pip install "psycopg[binary]" tqdm

Pour la vectorisation :
    pip install pgvector sentence-transformers

Exemple :
    python parse_legi_postgres.py Freemium_legi_global_20250713-140000.tar.gz \
        --dsn "postgresql://postgres:postgres@localhost:5432/legal"
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import tarfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover
    raise SystemExit('Module manquant. Installez-le avec: pip install "psycopg[binary]"') from exc

try:
    from tqdm import tqdm
except ImportError:  # tqdm reste facultatif
    tqdm = None


NAMESPACE = uuid.UUID("ad63b8fa-8a8f-4bd6-98d0-96055806ea75")
DEFAULT_EXCLUDED_STATES = {"ABROGE"}

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS corpus (
    id              uuid PRIMARY KEY,
    code            text NOT NULL UNIQUE,
    nom             text NOT NULL,
    source_url      text,
    source_archive  text,
    imported_at     timestamptz NOT NULL DEFAULT now(),
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS texte (
    id              uuid PRIMARY KEY,
    corpus_id       uuid NOT NULL REFERENCES corpus(id) ON DELETE CASCADE,
    source_id       text NOT NULL,
    type            text,
    titre           text,
    numero          text,
    nor             text,
    autorite        text,
    ministere       text,
    date_signature  date,
    date_publication date,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (corpus_id, source_id)
);

CREATE INDEX IF NOT EXISTS texte_corpus_idx ON texte(corpus_id);
CREATE INDEX IF NOT EXISTS texte_type_idx ON texte(type);
CREATE INDEX IF NOT EXISTS texte_titre_idx ON texte(titre);

CREATE TABLE IF NOT EXISTS unite (
    id              uuid PRIMARY KEY,
    corpus_id       uuid NOT NULL REFERENCES corpus(id) ON DELETE CASCADE,
    texte_id        uuid REFERENCES texte(id) ON DELETE SET NULL,
    source_id       text NOT NULL,
    type            text NOT NULL DEFAULT 'ARTICLE',
    numero          text,
    ordre           integer,
    chemin          jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (corpus_id, source_id)
);

CREATE INDEX IF NOT EXISTS unite_texte_idx ON unite(texte_id);
CREATE INDEX IF NOT EXISTS unite_numero_idx ON unite(numero);

CREATE TABLE IF NOT EXISTS version (
    id              uuid PRIMARY KEY,
    unite_id        uuid NOT NULL REFERENCES unite(id) ON DELETE CASCADE,
    source_id       text NOT NULL UNIQUE,
    etat            text,
    date_debut      date,
    date_fin        date,
    contenu         text NOT NULL,
    nota            text,
    checksum_sha256 text NOT NULL,
    source_archive  text,
    source_path     text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS version_unite_idx ON version(unite_id);
CREATE INDEX IF NOT EXISTS version_etat_idx ON version(etat);
CREATE INDEX IF NOT EXISTS version_dates_idx ON version(date_debut, date_fin);

CREATE TABLE IF NOT EXISTS relation_juridique (
    id                  uuid PRIMARY KEY,
    version_source_id   text NOT NULL,
    source_unite_id     uuid REFERENCES unite(id) ON DELETE CASCADE,
    type_relation       text NOT NULL,
    sens                text,
    cible_source_id     text,
    cible_texte_source_id text,
    cible_numero        text,
    cible_nature_texte  text,
    cible_numero_texte  text,
    cible_nor_texte     text,
    date_signature_texte date,
    libelle             text,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS relation_source_idx ON relation_juridique(source_unite_id);
CREATE INDEX IF NOT EXISTS relation_cible_idx ON relation_juridique(cible_source_id);
CREATE INDEX IF NOT EXISTS relation_type_idx ON relation_juridique(type_relation);

CREATE TABLE IF NOT EXISTS import_log (
    id              bigserial PRIMARY KEY,
    corpus_id       uuid NOT NULL REFERENCES corpus(id) ON DELETE CASCADE,
    source          text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    stats           jsonb NOT NULL DEFAULT '{}'::jsonb
);
"""


EMBEDDING_SCHEMA_SQL = r"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embedding_model (
    id              bigserial PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    dimension       integer NOT NULL,
    normalize       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS version_embedding (
    version_id       uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
    model_id         bigint NOT NULL REFERENCES embedding_model(id) ON DELETE CASCADE,
    content_checksum text NOT NULL,
    embedding        vector NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (version_id, model_id)
);

CREATE INDEX IF NOT EXISTS version_embedding_model_idx
    ON version_embedding(model_id);
"""


@dataclass
class NormalizedArticle:
    texte: Dict
    unite: Dict
    version: Dict
    relations: List[Dict] = field(default_factory=list)


def stable_uuid(kind: str, source_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"LEGI:{kind}:{source_id}")


def local_name(tag: str) -> str:
    return tag.split("}")[-1]


def text_of(element: Optional[ET.Element], default: str = "") -> str:
    if element is None or element.text is None:
        return default
    return element.text.strip()


def clean_xml_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    parts: List[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            tag = local_name(child.tag).lower()
            if tag in {"br", "p", "div", "li", "blockquote"}:
                parts.append("\n")
            walk(child)
            if tag in {"p", "div", "li", "blockquote"}:
                parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    walk(element)
    value = html.unescape("".join(parts)).replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def safe_date(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value or value.startswith("2999-"):
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return None


def hierarchy(root: ET.Element) -> List[Dict]:
    texte = root.find("./CONTEXTE/TEXTE")
    if texte is None:
        return []

    result: List[Dict] = []
    titre_txt = texte.find("./TITRE_TXT")
    if titre_txt is not None:
        title = (titre_txt.get("c_titre_court") or text_of(titre_txt)).strip()
        if title:
            result.append({
                "id": titre_txt.get("id_txt") or texte.get("cid"),
                "titre": title,
                "debut": titre_txt.get("debut"),
                "fin": titre_txt.get("fin"),
                "niveau": 0,
            })

    tm = texte.find("./TM")
    level = 1
    while tm is not None:
        t = tm.find("./TITRE_TM")
        if t is not None:
            title = text_of(t)
            if title:
                result.append({
                    "id": t.get("id"),
                    "titre": title,
                    "debut": t.get("debut"),
                    "fin": t.get("fin"),
                    "niveau": level,
                })
        level += 1
        tm = tm.find("./TM")
    return result


def canonical_unit_source_id(root: ET.Element, current_article_id: str) -> str:
    """Identifiant stable de l'article logique à travers ses versions.

    LEGI expose dans VERSIONS/VERSION/LIEN_ART la chaîne des LEGIARTI.
    On prend la version ayant la date de début la plus ancienne comme identifiant
    canonique de l'unité. Repli : LEGIARTI courant.
    """
    candidates: List[Tuple[str, str]] = []
    for link in root.findall("./VERSIONS/VERSION/LIEN_ART"):
        link_id = (link.get("id") or "").strip()
        if not link_id:
            continue
        debut = (link.get("debut") or "9999-12-31").strip()
        candidates.append((debut, link_id))
    if not candidates:
        return current_article_id
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][1]


def parse_article_xml(data: bytes, source_archive: str, source_path: str,
                      excluded_states: set[str]) -> Optional[NormalizedArticle]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    if local_name(root.tag).upper() != "ARTICLE":
        return None

    meta_commun = root.find("./META/META_COMMUN")
    meta_article = root.find("./META/META_SPEC/META_ARTICLE")
    if meta_commun is None or meta_article is None:
        return None

    article_id = text_of(meta_commun.find("./ID"))
    if not article_id:
        return None

    etat = text_of(meta_article.find("./ETAT")).upper()
    if etat in excluded_states:
        return None

    contenu = clean_xml_text(root.find("./BLOC_TEXTUEL/CONTENU"))
    if not contenu:
        return None

    contexte = root.find("./CONTEXTE/TEXTE")
    if contexte is None:
        return None

    texte_source_id = (contexte.get("cid") or "").strip()
    if not texte_source_id:
        # Quelques liens peuvent être incomplets ; sans identifiant de texte,
        # on conserve tout de même une clé déterministe dérivée de l'article.
        texte_source_id = f"UNKNOWN:{article_id}"

    titre_node = contexte.find("./TITRE_TXT")
    titre = ""
    if titre_node is not None:
        titre = (titre_node.get("c_titre_court") or text_of(titre_node)).strip()

    texte_id = stable_uuid("texte", texte_source_id)
    unit_source_id = canonical_unit_source_id(root, article_id)
    unite_id = stable_uuid("unite", unit_source_id)
    version_id = stable_uuid("version", article_id)
    path = hierarchy(root)

    texte = {
        "id": texte_id,
        "source_id": texte_source_id,
        "type": (contexte.get("nature") or "").strip().upper() or None,
        "titre": titre or None,
        "numero": (contexte.get("num") or "").strip() or None,
        "nor": (contexte.get("nor") or "").strip() or None,
        "autorite": (contexte.get("autorite") or "").strip() or None,
        "ministere": (contexte.get("ministere") or "").strip() or None,
        "date_signature": safe_date(contexte.get("date_signature") or ""),
        "date_publication": safe_date(contexte.get("date_publi") or ""),
        "metadata": {
            "titre_id": titre_node.get("id_txt") if titre_node is not None else None,
            "titre_debut": titre_node.get("debut") if titre_node is not None else None,
            "titre_fin": titre_node.get("fin") if titre_node is not None else None,
        },
    }

    ordre_raw = text_of(meta_article.find("./INT_ORDRE"))
    try:
        ordre = int(ordre_raw) if ordre_raw else None
    except ValueError:
        ordre = None

    unite = {
        "id": unite_id,
        "texte_id": texte_id,
        "source_id": unit_source_id,
        "type": "ARTICLE",
        "numero": text_of(meta_article.find("./NUM")) or None,
        "ordre": ordre,
        "chemin": path,
        "metadata": {
            "origine": text_of(meta_commun.find("./ORIGINE")),
            "nature": text_of(meta_commun.find("./NATURE")),
            "ancien_id": text_of(meta_commun.find("./ANCIEN_ID")),
            "url": text_of(meta_commun.find("./URL")),
            "type_article": text_of(meta_article.find("./TYPE")),
            "version_ids": [
                (x.get("id") or "").strip()
                for x in root.findall("./VERSIONS/VERSION/LIEN_ART")
                if (x.get("id") or "").strip()
            ],
        },
    }

    version = {
        "id": version_id,
        "unite_id": unite_id,
        "source_id": article_id,
        "etat": etat or None,
        "date_debut": safe_date(text_of(meta_article.find("./DATE_DEBUT"))),
        "date_fin": safe_date(text_of(meta_article.find("./DATE_FIN"))),
        "contenu": contenu,
        "nota": clean_xml_text(root.find("./NOTA/CONTENU")) or None,
        "checksum_sha256": hashlib.sha256(contenu.encode("utf-8")).hexdigest(),
        "source_archive": source_archive,
        "source_path": source_path,
        "metadata": {
            "type_article": text_of(meta_article.find("./TYPE")),
            "url": text_of(meta_commun.find("./URL")),
        },
    }

    relations: List[Dict] = []
    for pos, lien in enumerate(root.findall("./LIENS/LIEN")):
        typelien = (lien.get("typelien") or "INCONNU").strip().upper()
        sens = (lien.get("sens") or "").strip().lower() or None
        cible_id = (lien.get("id") or "").strip() or None
        cible_cid = (lien.get("cidtexte") or "").strip() or None
        libelle = " ".join("".join(lien.itertext()).split()) or None
        fingerprint = "|".join([
            article_id, str(pos), typelien, sens or "", cible_id or "",
            cible_cid or "", libelle or ""
        ])
        relations.append({
            "id": uuid.uuid5(NAMESPACE, f"LEGI:relation:{fingerprint}"),
            "version_source_id": article_id,
            "source_unite_id": unite_id,
            "type_relation": typelien,
            "sens": sens,
            "cible_source_id": cible_id,
            "cible_texte_source_id": cible_cid,
            "cible_numero": (lien.get("num") or "").strip() or None,
            "cible_nature_texte": (lien.get("naturetexte") or "").strip() or None,
            "cible_numero_texte": (lien.get("numtexte") or "").strip() or None,
            "cible_nor_texte": (lien.get("nortexte") or "").strip() or None,
            "date_signature_texte": safe_date(lien.get("datesignatexte") or ""),
            "libelle": libelle,
            "metadata": {},
        })

    return NormalizedArticle(texte=texte, unite=unite, version=version, relations=relations)


class LegiSource:
    """Abstraction d'entrée : dossier, XML unique, .tar.gz ou .tgz."""

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(path)

    @property
    def source_name(self) -> str:
        return self.path.name

    def iter_xml(self) -> Iterator[Tuple[str, bytes]]:
        if self.path.is_dir():
            for p in self.path.rglob("*.xml"):
                try:
                    yield str(p), p.read_bytes()
                except OSError:
                    continue
            return

        lower = self.path.name.lower()
        if lower.endswith(".xml"):
            yield self.path.name, self.path.read_bytes()
            return

        if lower.endswith((".tar.gz", ".tgz")):
            # r|gz = streaming strict : pas d'extraction et pas d'index global du tar.
            with tarfile.open(self.path, mode="r|gz") as tar:
                for member in tar:
                    if not member.isfile() or not member.name.lower().endswith(".xml"):
                        continue
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    try:
                        yield member.name, f.read()
                    except (OSError, EOFError):
                        continue
            return

        raise ValueError("Entrée supportée : dossier, .xml, .tar.gz ou .tgz")


class PostgresWriter:
    def __init__(self, dsn: str, corpus_code: str, corpus_name: str,
                 source_url: Optional[str], source_archive: str,
                 batch_size: int = 500):
        self.conn = psycopg.connect(dsn)
        self.batch_size = batch_size
        self.corpus_id = stable_uuid("corpus", corpus_code)
        self.corpus_code = corpus_code
        self.corpus_name = corpus_name
        self.source_url = source_url
        self.source_archive = source_archive
        self.textes: Dict[uuid.UUID, Dict] = {}
        self.unites: Dict[uuid.UUID, Dict] = {}
        self.versions: Dict[uuid.UUID, Dict] = {}
        self.relations: Dict[uuid.UUID, Dict] = {}

    def init_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute(
                """
                INSERT INTO corpus(id, code, nom, source_url, source_archive, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    nom = EXCLUDED.nom,
                    source_url = COALESCE(EXCLUDED.source_url, corpus.source_url),
                    source_archive = EXCLUDED.source_archive,
                    imported_at = now()
                """,
                (self.corpus_id, self.corpus_code, self.corpus_name,
                 self.source_url, self.source_archive, Jsonb({})),
            )
        self.conn.commit()

    def start_import_log(self, source: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO import_log(corpus_id, source) VALUES (%s, %s) RETURNING id",
                (self.corpus_id, source),
            )
            row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def finish_import_log(self, log_id: int, stats: Dict) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE import_log SET finished_at=now(), stats=%s WHERE id=%s",
                (Jsonb(stats), log_id),
            )
        self.conn.commit()

    def add(self, article: NormalizedArticle) -> None:
        self.textes[article.texte["id"]] = article.texte
        self.unites[article.unite["id"]] = article.unite
        self.versions[article.version["id"]] = article.version
        for relation in article.relations:
            self.relations[relation["id"]] = relation
        if len(self.versions) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.versions:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO texte(
                    id, corpus_id, source_id, type, titre, numero, nor,
                    autorite, ministere, date_signature, date_publication, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (corpus_id, source_id) DO UPDATE SET
                    type=COALESCE(EXCLUDED.type, texte.type),
                    titre=COALESCE(EXCLUDED.titre, texte.titre),
                    numero=COALESCE(EXCLUDED.numero, texte.numero),
                    nor=COALESCE(EXCLUDED.nor, texte.nor),
                    autorite=COALESCE(EXCLUDED.autorite, texte.autorite),
                    ministere=COALESCE(EXCLUDED.ministere, texte.ministere),
                    date_signature=COALESCE(EXCLUDED.date_signature, texte.date_signature),
                    date_publication=COALESCE(EXCLUDED.date_publication, texte.date_publication),
                    metadata=texte.metadata || EXCLUDED.metadata
                """,
                [(
                    x["id"], self.corpus_id, x["source_id"], x["type"], x["titre"],
                    x["numero"], x["nor"], x["autorite"], x["ministere"],
                    x["date_signature"], x["date_publication"], Jsonb(x["metadata"])
                ) for x in self.textes.values()],
            )
            cur.executemany(
                """
                INSERT INTO unite(
                    id, corpus_id, texte_id, source_id, type, numero, ordre, chemin, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (corpus_id, source_id) DO UPDATE SET
                    texte_id=COALESCE(EXCLUDED.texte_id, unite.texte_id),
                    type=EXCLUDED.type,
                    numero=COALESCE(EXCLUDED.numero, unite.numero),
                    ordre=COALESCE(EXCLUDED.ordre, unite.ordre),
                    chemin=CASE WHEN EXCLUDED.chemin='[]'::jsonb THEN unite.chemin ELSE EXCLUDED.chemin END,
                    metadata=unite.metadata || EXCLUDED.metadata
                """,
                [(
                    x["id"], self.corpus_id, x["texte_id"], x["source_id"], x["type"],
                    x["numero"], x["ordre"], Jsonb(x["chemin"]), Jsonb(x["metadata"])
                ) for x in self.unites.values()],
            )
            cur.executemany(
                """
                INSERT INTO version(
                    id, unite_id, source_id, etat, date_debut, date_fin, contenu, nota,
                    checksum_sha256, source_archive, source_path, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO UPDATE SET
                    unite_id=EXCLUDED.unite_id,
                    etat=EXCLUDED.etat,
                    date_debut=EXCLUDED.date_debut,
                    date_fin=EXCLUDED.date_fin,
                    contenu=EXCLUDED.contenu,
                    nota=EXCLUDED.nota,
                    checksum_sha256=EXCLUDED.checksum_sha256,
                    source_archive=EXCLUDED.source_archive,
                    source_path=EXCLUDED.source_path,
                    metadata=version.metadata || EXCLUDED.metadata
                """,
                [(
                    x["id"], x["unite_id"], x["source_id"], x["etat"], x["date_debut"],
                    x["date_fin"], x["contenu"], x["nota"], x["checksum_sha256"],
                    x["source_archive"], x["source_path"], Jsonb(x["metadata"])
                ) for x in self.versions.values()],
            )
            if self.relations:
                cur.executemany(
                    """
                    INSERT INTO relation_juridique(
                        id, version_source_id, source_unite_id, type_relation, sens,
                        cible_source_id, cible_texte_source_id, cible_numero,
                        cible_nature_texte, cible_numero_texte, cible_nor_texte,
                        date_signature_texte, libelle, metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        type_relation=EXCLUDED.type_relation,
                        sens=EXCLUDED.sens,
                        libelle=EXCLUDED.libelle,
                        metadata=relation_juridique.metadata || EXCLUDED.metadata
                    """,
                    [(
                        x["id"], x["version_source_id"], x["source_unite_id"],
                        x["type_relation"], x["sens"], x["cible_source_id"],
                        x["cible_texte_source_id"], x["cible_numero"], x["cible_nature_texte"],
                        x["cible_numero_texte"], x["cible_nor_texte"],
                        x["date_signature_texte"], x["libelle"], Jsonb(x["metadata"])
                    ) for x in self.relations.values()],
                )
        self.conn.commit()
        self.textes.clear()
        self.unites.clear()
        self.versions.clear()
        self.relations.clear()

    def close(self) -> None:
        self.flush()
        self.conn.close()


def _load_embedding_dependencies():
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        from pgvector import Vector
        from pgvector.psycopg import register_vector
    except ImportError as exc:
        raise SystemExit(
            "Dépendances pgvector manquantes. Installez: "
            "pip install pgvector sentence-transformers numpy"
        ) from exc
    return np, SentenceTransformer, Vector, register_vector


def _embedding_text(row: Dict) -> str:
    """Construit le document vectorisé sans dépendre d'un code particulier."""
    chemin = row.get("chemin") or []
    if isinstance(chemin, str):
        try:
            chemin = json.loads(chemin)
        except Exception:
            chemin = []
    labels = []
    for item in chemin:
        if isinstance(item, dict):
            title = (item.get("titre") or "").strip()
            if title:
                labels.append(title)
        elif item:
            labels.append(str(item))

    header = []
    if row.get("type_texte"):
        header.append(str(row["type_texte"]))
    if row.get("titre"):
        header.append(str(row["titre"]))
    if row.get("numero"):
        header.append(f"Article {row['numero']}")
    if labels:
        header.append(" > ".join(labels))
    return "\n".join(header) + "\n\n" + (row.get("contenu") or "")


def _safe_index_name(model_name: str, dimension: int) -> str:
    digest = hashlib.sha1(model_name.encode("utf-8")).hexdigest()[:10]
    return f"version_embedding_hnsw_{dimension}_{digest}"


def vectorize_vigueur(
    dsn: str,
    model_name: str,
    batch_size: int = 64,
    fetch_size: int = 1000,
    device: Optional[str] = None,
    create_hnsw: bool = True,
) -> Dict:
    """Vectorise uniquement les versions ETAT=VIGUEUR.

    Reprenable : une ligne dont le checksum n'a pas changé et qui possède déjà
    un embedding pour le même modèle est ignorée.
    """
    np, SentenceTransformer, Vector, register_vector = _load_embedding_dependencies()

    print(f"Chargement du modèle d'embeddings : {model_name}")
    model = SentenceTransformer(model_name, device=device) if device else SentenceTransformer(model_name)
    dimension = int(model.get_sentence_embedding_dimension())

    conn = psycopg.connect(dsn)
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)
        conn.execute(EMBEDDING_SCHEMA_SQL)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO embedding_model(name, dimension, normalize, metadata)
                VALUES (%s, %s, true, %s)
                ON CONFLICT (name) DO UPDATE SET
                    dimension = EXCLUDED.dimension,
                    normalize = EXCLUDED.normalize,
                    metadata = embedding_model.metadata || EXCLUDED.metadata
                RETURNING id
                """,
                (model_name, dimension, Jsonb({"source": "sentence-transformers"})),
            )
            model_id = int(cur.fetchone()[0])
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM version v
                LEFT JOIN version_embedding ve
                  ON ve.version_id = v.id AND ve.model_id = %s
                WHERE v.etat = 'VIGUEUR'
                  AND (ve.version_id IS NULL OR ve.content_checksum <> v.checksum_sha256)
                """,
                (model_id,),
            )
            total = int(cur.fetchone()[0])

        stats = {
            "model": model_name,
            "dimension": dimension,
            "etat": "VIGUEUR",
            "a_vectoriser": total,
            "vectorises": 0,
            "hnsw": False,
        }
        if total == 0:
            print("Tous les embeddings VIGUEUR sont déjà à jour.")
            return stats

        progress = tqdm(total=total, desc="Embeddings VIGUEUR", unit="version") if tqdm else None
        last_id = None
        while True:
            params = [model_id]
            seek = ""
            if last_id is not None:
                seek = "AND v.id > %s"
                params.append(last_id)
            params.append(fetch_size)

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        v.id, v.checksum_sha256, v.contenu,
                        u.numero, u.chemin,
                        t.titre, t.type AS type_texte
                    FROM version v
                    JOIN unite u ON u.id = v.unite_id
                    JOIN texte t ON t.id = u.texte_id
                    LEFT JOIN version_embedding ve
                      ON ve.version_id = v.id AND ve.model_id = %s
                    WHERE v.etat = 'VIGUEUR'
                      AND (ve.version_id IS NULL OR ve.content_checksum <> v.checksum_sha256)
                      {seek}
                    ORDER BY v.id
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
                cols = [d.name for d in cur.description]

            if not rows:
                break

            docs = [dict(zip(cols, row)) for row in rows]
            for start in range(0, len(docs), batch_size):
                batch = docs[start:start + batch_size]
                texts = [_embedding_text(x) for x in batch]
                vectors = model.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                records = [
                    (
                        item["id"], model_id, item["checksum_sha256"],
                        Vector(np.asarray(vec, dtype=np.float32)),
                    )
                    for item, vec in zip(batch, vectors)
                ]
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO version_embedding(
                            version_id, model_id, content_checksum, embedding
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (version_id, model_id) DO UPDATE SET
                            content_checksum = EXCLUDED.content_checksum,
                            embedding = EXCLUDED.embedding,
                            updated_at = now()
                        """,
                        records,
                    )
                conn.commit()
                stats["vectorises"] += len(batch)
                if progress:
                    progress.update(len(batch))

            last_id = docs[-1]["id"]

        if progress:
            progress.close()

        if create_hnsw:
            # La colonne est vector sans dimension pour accepter plusieurs modèles.
            # L'index HNSW est donc une expression dimensionnée et partielle par modèle.
            index_name = _safe_index_name(model_name, dimension)
            model_id_sql = int(model_id)
            index_sql = f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON version_embedding
                USING hnsw ((embedding::vector({dimension})) vector_cosine_ops)
                WHERE model_id = {model_id_sql}
            """
            print(f"Création/vérification de l'index HNSW : {index_name}")
            conn.execute(index_sql)
            conn.commit()
            stats["hnsw"] = True
            stats["hnsw_index"] = index_name

        return stats
    finally:
        conn.close()


def import_legi(args: argparse.Namespace) -> Dict:
    source = LegiSource(args.source)
    excluded_states = {x.upper() for x in args.exclude_states}
    writer = PostgresWriter(
        dsn=args.dsn,
        corpus_code=args.corpus_code,
        corpus_name=args.corpus_name,
        source_url=args.source_url,
        source_archive=source.source_name,
        batch_size=args.batch_size,
    )
    writer.init_schema()
    log_id = writer.start_import_log(str(source.path))

    stats = {
        "xml_scannes": 0,
        "articles_xml": 0,
        "articles_importes": 0,
        "articles_ignores": 0,
        "relations_importees": 0,
        "erreurs": 0,
        "etats_exclus": sorted(excluded_states),
    }

    iterator: Iterable[Tuple[str, bytes]] = source.iter_xml()
    if tqdm is not None:
        iterator = tqdm(iterator, desc="Import LEGI", unit="xml")

    try:
        for source_path, data in iterator:
            stats["xml_scannes"] += 1
            # Filtre rapide pour éviter ET.fromstring sur les XML non ARTICLE.
            head = data[:2048].upper()
            if b"<ARTICLE" not in head:
                continue
            stats["articles_xml"] += 1
            try:
                article = parse_article_xml(
                    data=data,
                    source_archive=source.source_name,
                    source_path=source_path,
                    excluded_states=excluded_states,
                )
            except Exception:
                stats["erreurs"] += 1
                if args.fail_fast:
                    raise
                continue

            if article is None:
                stats["articles_ignores"] += 1
                continue

            writer.add(article)
            stats["articles_importes"] += 1
            stats["relations_importees"] += len(article.relations)

        writer.flush()
        writer.finish_import_log(log_id, stats)
    finally:
        writer.close()

    return stats


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Importe un corpus LEGI dans PostgreSQL sans extraire le TGZ"
    )
    p.add_argument("source", help="Dossier, fichier XML, .tar.gz ou .tgz LEGI")
    p.add_argument(
        "--dsn",
        default="postgresql://postgres:postgres@localhost:5432/legal",
        help="DSN PostgreSQL",
    )
    p.add_argument("--corpus-code", default="LEGI")
    p.add_argument("--corpus-name", default="Légifrance - LEGI consolidé")
    p.add_argument(
        "--source-url",
        default="https://echanges.dila.gouv.fr/OPENDATA/LEGI/",
    )
    p.add_argument(
        "--exclude-states",
        nargs="+",
        default=sorted(DEFAULT_EXCLUDED_STATES),
        help="Etats à exclure (défaut: ABROGE)",
    )
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument(
        "--no-vectorize",
        action="store_true",
        help="N'effectue pas la vectorisation pgvector après l'import",
    )
    p.add_argument(
        "--embedding-model",
        default="../paraphrase-multilingual-MiniLM-L12-v2",
        help="Modèle SentenceTransformer local ou Hugging Face",
    )
    p.add_argument("--embedding-batch-size", type=int, default=64)
    p.add_argument("--embedding-fetch-size", type=int, default=1000)
    p.add_argument("--embedding-device", default=None, help="Ex: cuda, cpu ; auto si omis")
    p.add_argument(
        "--no-hnsw",
        action="store_true",
        help="Ne crée pas l'index HNSW après vectorisation",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    stats = import_legi(args)
    print("\nImport terminé")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if not args.no_vectorize:
        vector_stats = vectorize_vigueur(
            dsn=args.dsn,
            model_name=args.embedding_model,
            batch_size=args.embedding_batch_size,
            fetch_size=args.embedding_fetch_size,
            device=args.embedding_device,
            create_hnsw=not args.no_hnsw,
        )
        print("\nVectorisation terminée")
        print(json.dumps(vector_stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
