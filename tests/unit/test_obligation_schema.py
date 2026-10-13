import copy
import pytest
from legal.obligations import OBLIGATION_JSON_SCHEMA, validate_obligation, ObligationValidationError


def sample():
    return dict(actor="L'exploitant", modality="OBLIGATION", action="transmettre", object="le rapport",
                conditions=[], exceptions=[], deadline="avant le 31 mars", frequency=None,
                threshold=None, territorial_scope=None, temporal_scope=None,
                source_excerpt="transmettre le rapport", span_start=18, span_end=38)


def test_valid_with_source():
    p = sample()
    source = "L'exploitant doit transmettre le rapport avant le 31 mars"
    p['span_start'] = source.index('transmettre le rapport')
    p['span_end'] = p['span_start'] + len(p['source_excerpt'])
    assert validate_obligation(p, source_text=source) == p

@pytest.mark.parametrize('change', [
    lambda p: p.update(modality='OTHER'),
    lambda p: p.update(action=' '),
    lambda p: p.update(conditions='test'),
    lambda p: p.update(span_start=None),
    lambda p: p.update(span_start=True),
    lambda p: p.update(span_end=2),
    lambda p: p.update(untrusted='extra'),
    lambda p: p.pop('actor'),
])
def test_reject_invalid(change):
    p = sample()
    change(p)
    with pytest.raises(ObligationValidationError):
        validate_obligation(p)


def test_reject_wrong_evidence():
    p = sample()
    with pytest.raises(ObligationValidationError):
        validate_obligation(p, source_text='different text')


def test_schema_strict():
    assert OBLIGATION_JSON_SCHEMA['additionalProperties'] is False
    assert set(OBLIGATION_JSON_SCHEMA['required']) == set(OBLIGATION_JSON_SCHEMA['properties'])
