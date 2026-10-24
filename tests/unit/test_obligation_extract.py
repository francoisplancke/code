import json
import pytest
from legal.obligations.extract import deterministic, llm_extract, checksum
from legal.obligations.schema import ObligationValidationError

TEXT = 'L’exploitant doit transmettre le rapport avant le 31 mars.'

def test_deterministic_citation():
    items = deterministic(TEXT)
    assert len(items) == 1
    ob = items[0].obligation
    assert ob['modality'] == 'OBLIGATION'
    assert TEXT[ob['span_start']:ob['span_end']] == ob['source_excerpt']

def test_no_cue():
    assert deterministic('Ce texte entre en vigueur demain.') == []

def test_llm_strict_valid():
    ob = deterministic(TEXT)[0].obligation
    items, _ = llm_extract(TEXT, lambda messages, temperature: json.dumps({'obligations':[ob]}))
    assert len(items) == 1

def test_llm_hallucinated_excerpt_rejected():
    ob = deterministic(TEXT)[0].obligation
    ob['source_excerpt'] = 'Citation inventée'
    diagnostics = {}
    items, _ = llm_extract(TEXT, lambda messages, temperature: json.dumps({'obligations':[ob]}), diagnostics=diagnostics)
    assert items == []
    assert diagnostics['rejected'] == 1

def test_llm_invalid_envelope():
    with pytest.raises(ObligationValidationError):
        llm_extract(TEXT, lambda messages, temperature: '{}')

def test_long_text_refused():
    with pytest.raises(ValueError):
        llm_extract('x'*12001, lambda *args, **kwargs: '{}')

def test_checksum_stable():
    assert checksum(TEXT) == checksum(TEXT)


def test_llm_mixed_valid_invalid():
    valid = deterministic(TEXT)[0].obligation
    invalid = dict(valid, action=None)
    diagnostics = {}
    items, _ = llm_extract(TEXT, lambda messages, temperature: json.dumps({'obligations': [invalid, valid]}), diagnostics=diagnostics)
    assert len(items) == 1
    assert diagnostics['candidates'] == 2
    assert diagnostics['rejected'] == 1
