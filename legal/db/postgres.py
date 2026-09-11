from __future__ import annotations

from typing import Any


def safe_dsn(dsn: str) -> str:
    """Masque le mot de passe d'un DSN avant journalisation."""
    if "://" not in dsn or "@" not in dsn:
        return dsn
    prefix, rest = dsn.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    if ":" in credentials:
        user = credentials.split(":", 1)[0]
        return f"{prefix}://{user}:***@{host}"
    return dsn


class PostgresDatabase:
    """Petit adaptateur de connexion PostgreSQL, injectable pour les tests."""

    def __init__(self, dsn: str, connection: Any | None = None):
        self.dsn = dsn
        if connection is not None:
            self.connection = connection
            return

        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:  # pragma: no cover - dépend de l'environnement
            raise RuntimeError(
                'Modules PostgreSQL manquants. Installez "psycopg[binary]" et pgvector.'
            ) from exc

        self.connection = psycopg.connect(dsn)
        register_vector(self.connection)

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "PostgresDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
