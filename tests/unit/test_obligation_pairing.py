import pytest
from legal.obligations.pairing import tokens, score_pair, pair_scope

def test_accents_and_stopwords():
    assert tokens('Les déclarations obligatoires') == {'declarations', 'obligatoires'}

def test_exact_match():
    a={'action':'transmettre rapport annuel','object':'rapport annuel','actor':'exploitant','modality':'OBLIGATION'}
    score, features=score_pair(a,a)
    assert score == 1.0 and features['same_modality']

def test_different_modalities_penalized():
    a={'action':'transmettre rapport annuel','modality':'OBLIGATION'}
    b={**a,'modality':'PERMISSION'}
    assert score_pair(a,b)[0] < score_pair(a,a)[0]

def test_missing_fields_no_false_perfect_score():
    assert score_pair({'action':None},{'action':None})[0] == 0

def test_conditions_preserved():
    a={'action':'declarer','conditions':['si possible'],'modality':'OBLIGATION'}
    b={'action':'declarer','conditions':[],'modality':'OBLIGATION'}
    assert score_pair(a,b)[1]['eu_conditions'] == ['si possible']

def test_reject_missing_scope_before_db():
    with pytest.raises(ValueError):
        pair_scope(None,eu_celex='32024L0001',fr_version_ids=[],scope_reference='manual')

def test_reject_invalid_origin_before_db():
    with pytest.raises(ValueError):
        pair_scope(None,eu_celex='32024L0001',fr_version_ids=['x'],scope_reference='manual',scope_origin='AUTO_GUESSED')
