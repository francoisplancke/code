from pathlib import Path

from legal.domain import NormalizedArticle


ROOT = Path(__file__).resolve().parents[2]


def test_domain_normalized_article_keeps_r0_shape():
    article = NormalizedArticle(
        texte={"source_id": "LEGITEXT"},
        unite={"source_id": "LEGIARTI"},
        version={"source_id": "LEGIARTI-V1"},
    )
    assert article.texte["source_id"] == "LEGITEXT"
    assert article.relations == []


def test_r1_package_boundaries_exist():
    assert (ROOT / "legal" / "domain" / "norm.py").is_file()
    assert (ROOT / "legal" / "ingestion" / "legi.py").is_file()
    assert (ROOT / "legal" / "db" / "postgres.py").is_file()
    assert (ROOT / "legal" / "retrieval" / "hybrid.py").is_file()


def test_legacy_ingestion_cli_is_wrapper():
    source = (ROOT / "parse_legi_postgres.py").read_text(encoding="utf-8")
    assert "from legal.ingestion.legi import" in source
    assert "main()" in source
