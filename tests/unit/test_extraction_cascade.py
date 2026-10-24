from legal.obligations.cascade import compare, is_credit_error
from legal.obligations.extract import Extraction
from urllib.error import HTTPError
from io import BytesIO

def item(action):
    return Extraction({'modality':'OBLIGATION','actor':None,'action':action,
                       'object':'X','deadline':None,'frequency':None,'threshold':None},'LLM',None)

def test_agreement():
    assert compare([item('Déclarer')],[item('déclarer')])['agreement']=='EXACT_FIELDS'

def test_missing():
    result=compare([], [item('déclarer')])
    assert result['reference_only']==1

def test_credit_402():
    assert is_credit_error(HTTPError('x',402,'payment',{},BytesIO(b'')))

def test_rate_limit_not_necessarily_credit():
    assert not is_credit_error(HTTPError('x',429,'rate',{},BytesIO(b'rate limit')))

def test_quota():
    assert is_credit_error(HTTPError('x',429,'quota',{},BytesIO(b'{"error":"insufficient_quota"}')))
