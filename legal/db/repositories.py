from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddingModelRecord:
    id: int
    dimension: int
    normalize: bool


class EmbeddingModelRepository:
    """Accès aux métadonnées du modèle et au comptage des embeddings."""

    def __init__(self, connection: Any):
        self.connection = connection

    def get_by_name(self, model_name: str) -> EmbeddingModelRecord | None:
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, dimension, normalize
                FROM embedding_model
                WHERE name = %s
                """,
                (model_name,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return EmbeddingModelRecord(
            id=int(row[0]), dimension=int(row[1]), normalize=bool(row[2])
        )

    def count_versions(self, model_id: int, etat: str) -> int:
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM version_embedding ve
                JOIN version v ON v.id = ve.version_id
                WHERE ve.model_id = %s AND v.etat = %s
                """,
                (model_id, etat),
            )
            return int(cur.fetchone()[0])
