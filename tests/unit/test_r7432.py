import json
import pytest
from legal.obligations.extract import resolve_citation, llm_extract
from legal.obligations.schema import ObligationValidationError
from legal.obligations.cascade import compare


def candidate(excerpt, start=0, end=0):
    return dict(actor=None, modality='OBLIGATION', action='déclarer', object='un rapport',
                conditions=[], exceptions=[], deadline=None, frequency=None, threshold=None,
                territorial_scope=None, temporal_scope=None, source_excerpt=excerpt,
                span_start=start, span_end=end)


def test_wrong_offsets_repaired():
    text='Préambule. La société doit déclarer un rapport.'
    item, method=resolve_citation(text,candidate('La société doit déclarer un rapport.'))
    assert method=='EXACT'
    assert text[item['span_start']:item['span_end']]==item['source_excerpt']


def test_half_open_unicode():
    text='État : l’entreprise doit déclarer.'
    item, _=resolve_citation(text,candidate('l’entreprise doit déclarer.', 0, 0))
    assert item['span_end']-item['span_start']==len(item['source_excerpt'])


def test_typography_normalized_and_canonical():
    text='L’entreprise  doit\n déclarer.'
    item, method=resolve_citation(text,candidate("L'entreprise doit déclarer."))
    assert method=='TYPOGRAPHY'
    assert item['source_excerpt']==text


def test_repeated_excerpt_rejected():
    with pytest.raises(ObligationValidationError,match='ambiguous'):
        resolve_citation('doit agir; doit agir',candidate('doit agir'))


def test_absent_rejected():
    with pytest.raises(ObligationValidationError,match='absent'):
        resolve_citation('Aucun devoir ici',candidate('doit déclarer'))


def test_invalid_agreement_never_exact():
    assert compare([],[],local_valid=False,reference_valid=False)['agreement']=='INVALID_COMPARISON'


def test_valid_empty_agreement():
    assert compare([],[],local_valid=True,reference_valid=True)['agreement']=='EXACT_FIELDS'


def test_llm_extraction_repairs_bad_offsets():
    text='La société doit déclarer un rapport.'
    result={'obligations':[candidate(text,0,0)]}
    diag={}
    items,_=llm_extract(text,lambda *args,**kwargs:json.dumps(result),diagnostics=diag)
    assert len(items)==1
    assert items[0].obligation['span_end']==len(text)
    assert diag['anchored']['EXACT']==1


def test_llm_partial_rejects_bad_excerpt():
    text='La société doit déclarer un rapport.'
    result={'obligations':[candidate(text,0,0),candidate('obligation inventée',0,0)]}
    diag={}
    items,_=llm_extract(text,lambda *args,**kwargs:json.dumps(result),diagnostics=diag)
    assert len(items)==1 and diag['rejected']==1
