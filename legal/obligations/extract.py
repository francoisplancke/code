"""R7.4.2: evidence-checked obligation extraction; no autonomous legal conclusions."""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable
from .schema import validate_obligation, ObligationValidationError

PIPELINE_VERSION = 'r7.4.2-v1'
PROMPT_VERSION = 'obligation-extraction-fr-v1'
PATTERN = re.compile(r'\b(doit|doivent|est tenu(?:e)? de|sont tenus de|ne peut pas|ne peuvent pas|est interdit de|sont interdits de)\b', re.I)
SENTENCE = re.compile(r'[^.!?\n]+(?:[.!?]|$)', re.U)

@dataclass(frozen=True)
class Extraction:
    obligation: dict
    extractor: str
    confidence: float | None
    raw_output: dict | None = None


def _empty(excerpt, start, end, modality, action):
    return dict(actor=None, modality=modality, action=action, object=None,
                conditions=[], exceptions=[], deadline=None, frequency=None,
                threshold=None, territorial_scope=None, temporal_scope=None,
                source_excerpt=excerpt, span_start=start, span_end=end)


def deterministic(text: str) -> list[Extraction]:
    """High-precision cue-based candidates, NOT a complete legal parser."""
    found = []
    for match in SENTENCE.finditer(text):
        excerpt = match.group().strip()
        cue = PATTERN.search(excerpt)
        if not cue:
            continue
        start = text.find(excerpt, match.start(), match.end())
        tail = excerpt[cue.end():].strip(' :;,')
        if not tail:
            continue
        modality = 'PROHIBITION' if ('ne peut' in cue.group().lower() or 'interdit' in cue.group().lower()) else 'OBLIGATION'
        value = _empty(excerpt, start, start + len(excerpt), modality, tail)
        found.append(Extraction(validate_obligation(value, source_text=text), 'DETERMINISTIC', None))
    return found

SYSTEM_PROMPT = '''Tu extrais des obligations juridiques hypothétiques, sans avis juridique.
Réponds UNIQUEMENT par un objet JSON {"obligations": [...]}.
Chaque élément possède exactement les champs actor, modality, action, object,
conditions, exceptions, deadline, frequency, threshold, territorial_scope,
temporal_scope, source_excerpt, span_start, span_end.
modalité: OBLIGATION, PROHIBITION, PERMISSION ou EXEMPTION.
Les champs inconnus valent null, conditions/exceptions valent des listes.
source_excerpt doit être une citation littérale exacte du texte source.
span_start/span_end sont les positions Unicode [début, fin) dans le texte fourni.
N'invente ni obligation, ni acteur, ni délai. Si aucune obligation, renvoie une liste vide.'''


def llm_extract(text: str, chat_fn: Callable, *, max_chars: int = 12000) -> tuple[list[Extraction], str]:
    if len(text) > max_chars:
        raise ValueError('source too long; segment before LLM extraction')
    response = chat_fn([{'role':'system','content':SYSTEM_PROMPT},
                        {'role':'user','content':'Texte source:\n' + text}], temperature=0.0)
    cleaned = response.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', cleaned).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict) or set(data) != {'obligations'} or not isinstance(data['obligations'], list):
        raise ObligationValidationError('expected {"obligations": [...]}')
    if len(data['obligations']) > 100:
        raise ObligationValidationError('too many obligations')
    items = []
    for item in data['obligations']:
        print("OBLIGATION LLM BRUTE:", json.dumps(item, ensure_ascii=False, indent=2))
        normalized = validate_obligation(item, source_text=text)
        if normalized['span_start'] is None:
            # Reject ambiguous offsets; exact citation must identify one location.
            if text.count(normalized['source_excerpt']) != 1:
                raise ObligationValidationError('ambiguous excerpt without offsets')
            start = text.index(normalized['source_excerpt'])
            normalized['span_start'] = start
            normalized['span_end'] = start + len(normalized['source_excerpt'])
        items.append(Extraction(normalized, 'LLM', None, {'response': data}))
    return items, response


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
