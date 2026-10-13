"""Ingestion et normalisation des corpus juridiques."""

from .legi import LegiSource, PostgresWriter, parse_article_xml

__all__ = ["LegiSource", "PostgresWriter", "parse_article_xml"]
