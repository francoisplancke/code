"""Objets métier stables du corpus juridique.

R1 ne change pas encore la représentation persistée en PostgreSQL. Ce module
centralise seulement les objets de passage entre ingestion et couches métier,
afin d'éviter que le parseur LEGI devienne le propriétaire du modèle domaine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedArticle:
    """Article LEGI normalisé avant persistance.

    Les dictionnaires conservent volontairement le format R0 pour garantir
    l'absence de changement fonctionnel dans l'importeur pendant R1.
    """

    texte: dict[str, Any]
    unite: dict[str, Any]
    version: dict[str, Any]
    relations: list[dict[str, Any]] = field(default_factory=list)
