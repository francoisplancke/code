import pytest
from legal.obligations.evidence import verify_evidence
from legal.obligations.extract import checksum

TEXT = "Les investissements de caractère social font, si possible, l'objet d'un relevé séparé et global."

def check(**overrides):
    data = dict(source_text=TEXT, source_checksum=checksum(TEXT), source_excerpt=TEXT, span_start=0, span_end=len(TEXT))
    data.update(overrides)
    return verify_evidence(**data)

def test_verified(): assert check() == ('VERIFIED', [])
def test_missing(): assert check(source_text=None)[0] == 'SOURCE_MISSING'
def test_changed_source(): assert 'SOURCE_CHECKSUM_MISMATCH' in check(source_checksum='0'*64)[1]
def test_bad_excerpt(): assert 'EXCERPT_MISMATCH' in check(source_excerpt='inventé')[1]
def test_bad_span(): assert 'INVALID_SPAN' in check(span_start=0, span_end=0)[1]
def test_null_span(): assert 'INVALID_SPAN' in check(span_start=None)[1]
def test_empty_excerpt(): assert 'EMPTY_EXCERPT' in check(source_excerpt='')[1]
def test_unicode_offsets():
    text = 'école: obligation'
    assert verify_evidence(source_text=text, source_checksum=checksum(text), source_excerpt='obligation', span_start=7, span_end=17) == ('VERIFIED', [])
