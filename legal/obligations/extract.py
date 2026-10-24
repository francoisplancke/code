"""R7.4.2: evidence-checked obligation extraction; no autonomous legal conclusions."""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable
from .schema import validate_obligation, ObligationValidationError

PIPELINE_VERSION = 'r7.4.3.2-v1'
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
N'invente ni obligation, ni acteur, ni délai. Si aucune obligation, renvoie une liste vide.
Une dépense ou un thème n'est pas à lui seul une obligation. action doit décrire un comportement explicite.
N'utilise jamais une référence générique comme citation. Ne produis que des citations littérales continues.'''



def resolve_citation(source_text: str, candidate: dict) -> tuple[dict, str]:
    """Canonicalize a uniquely located literal citation, ignoring model offsets.

    Return (candidate copy, anchoring method). Never invent evidence.
    """
    excerpt = candidate.get('source_excerpt')
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise ObligationValidationError('source_excerpt must be a nonempty string')
    start = source_text.find(excerpt)
    if start >= 0:
        if source_text.find(excerpt, start + 1) >= 0:
            raise ObligationValidationError('ambiguous literal excerpt')
        result = dict(candidate)
        result['span_start'], result['span_end'] = start, start + len(excerpt)
        return result, 'EXACT'

    # Typographic normalization with an exact index map back to canonical source.
    # Only normalize whitespace runs and common apostrophe variants; never
    # remove or reorder substantive characters.
    def normalize_with_map(value: str):
        chars, starts, ends = [], [], []
        i = 0
        while i < len(value):
            ch = value[i]
            if ch.isspace() or ch == '\u00a0':
                j = i + 1
                while j < len(value) and value[j].isspace():
                    j += 1
                chars.append(' ')
                starts.append(i)
                ends.append(j)
                i = j
            else:
                chars.append("'" if ch in ('\u2019', '\u2018', '\u02bc') else ch)
                starts.append(i)
                ends.append(i + 1)
                i += 1
        return ''.join(chars), starts, ends

    normalized_source, starts, ends = normalize_with_map(source_text)
    normalized_excerpt, _, _ = normalize_with_map(excerpt)
    idx = normalized_source.find(normalized_excerpt)
    if idx < 0:
        raise ObligationValidationError('excerpt absent from source after typography normalization')
    if normalized_source.find(normalized_excerpt, idx + 1) >= 0:
        raise ObligationValidationError('ambiguous normalized excerpt')
    begin, finish = starts[idx], ends[idx + len(normalized_excerpt) - 1]
    result = dict(candidate)
    result['source_excerpt'] = source_text[begin:finish]
    result['span_start'], result['span_end'] = begin, finish
    return result, 'TYPOGRAPHY'

def llm_extract(text: str, chat_fn: Callable, *, max_chars: int = 12000, diagnostics: dict | None = None) -> tuple[list[Extraction], str]:
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
    rejected = []
    anchored = {'EXACT': 0, 'TYPOGRAPHY': 0}
    for index, item in enumerate(data['obligations']):
        try:
            anchored_item, method = resolve_citation(text, item)
            normalized = validate_obligation(anchored_item, source_text=text)
            anchored[method] += 1
        except ObligationValidationError as exc:
            rejected.append({'index': index, 'reason': str(exc)})
            continue
        items.append(Extraction(normalized, 'LLM', None, {'response': data}))
    if diagnostics is not None:
        diagnostics.update({'candidates': len(data['obligations']), 'rejected': len(rejected), 'rejections': rejected, 'anchored': anchored})
    return items, response


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
