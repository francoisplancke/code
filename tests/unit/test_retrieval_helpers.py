from legal.db.postgres import safe_dsn
from legal.retrieval.hybrid import (
    _score_hybrid_rows,
    format_chemin_hierarchique,
    lexical_query,
)


def test_safe_dsn_masks_password():
    assert safe_dsn("postgresql://alice:secret@localhost:5432/legal") == \
        "postgresql://alice:***@localhost:5432/legal"


def test_safe_dsn_keeps_non_url():
    assert safe_dsn("dbname=legal") == "dbname=legal"


def test_lexical_query_collapses_whitespace():
    assert lexical_query("  durée   maximale\n quotidienne ") == "durée maximale quotidienne"


def test_format_hierarchy_json_and_deduplicate_consecutive_titles():
    value = '[{"titre":"Livre I"},{"titre":"Livre I"},{"titre":"Titre II"}]'
    assert format_chemin_hierarchique(value) == "Livre I > Titre II"


def test_format_hierarchy_supports_old_python_repr():
    value = "[{'titre': 'Livre I'}, {'libelle': 'Chapitre II'}]"
    assert format_chemin_hierarchique(value) == "Livre I > Chapitre II"


def test_hybrid_score_matches_historical_formula():
    rows = [
        {"id": "a", "vector_score": 0.8, "lexical_score": 2.0},
        {"id": "b", "vector_score": 0.9, "lexical_score": 1.0},
    ]
    ranked = _score_hybrid_rows(rows, lexical_weight=0.25, k=2)
    # a = .75*.8 + .25*1 = .85 ; b = .75*.9 + .25*.5 = .80
    assert [r["id"] for r in ranked] == ["a", "b"]
    assert round(ranked[0]["score"], 6) == 0.85
    assert round(ranked[1]["score"], 6) == 0.80


def test_hybrid_score_clamps_weight():
    rows = [{"id": "a", "vector_score": 0.2, "lexical_score": 5.0}]
    ranked = _score_hybrid_rows(rows, lexical_weight=2.0, k=1)
    assert ranked[0]["score"] == 1.0
