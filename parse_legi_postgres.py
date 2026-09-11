"""Wrapper CLI rétrocompatible de l'importeur LEGI.

L'implémentation R1 vit désormais dans :mod:`legal.ingestion.legi`.
Ce module conserve les imports historiques et le point d'entrée CLI.
"""
from legal.ingestion.legi import *  # noqa: F401,F403
from legal.ingestion.legi import main


if __name__ == "__main__":
    main()
