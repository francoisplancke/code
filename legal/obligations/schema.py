"""Strict provider-independent output contract for one extracted legal obligation.

Source identity, run provenance, confidence and human review are managed by the
storage layer, never trusted from an LLM response.
"""
from __future__ import annotations

from typing import Any

MODALITIES = ("OBLIGATION", "PROHIBITION", "PERMISSION", "EXEMPTION")
_FIELDS = (
    "actor", "modality", "action", "object", "conditions", "exceptions",
    "deadline", "frequency", "threshold", "territorial_scope", "temporal_scope",
    "source_excerpt", "span_start", "span_end",
)

OBLIGATION_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "LegalObligationExtractionV1",
    "type": "object",
    "additionalProperties": False,
    "required": list(_FIELDS),
    "properties": {
        **{name: {"type": ["string", "null"]} for name in (
            "actor", "object", "deadline", "frequency", "threshold", "territorial_scope", "temporal_scope"
        )},
        "modality": {"type": "string", "enum": list(MODALITIES)},
        "action": {"type": "string", "minLength": 1},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "exceptions": {"type": "array", "items": {"type": "string"}},
        "source_excerpt": {"type": "string", "minLength": 1},
        "span_start": {"type": ["integer", "null"], "minimum": 0},
        "span_end": {"type": ["integer", "null"], "minimum": 1},
    },
}

class ObligationValidationError(ValueError):
    """Extracted payload violates the R7.4.1 contract."""


def validate_obligation(payload: Any, *, source_text: str | None = None) -> dict[str, Any]:
    """Validate and return a copy; no third-party JSON-schema dependency.

    If source_text is provided, excerpt and offsets must match it exactly.
    Offsets use Python Unicode character indices, [start, end).
    """
    if not isinstance(payload, dict):
        raise ObligationValidationError("obligation must be an object")
    if set(payload) != set(_FIELDS):
        raise ObligationValidationError(f"missing={sorted(set(_FIELDS)-set(payload))}; unknown={sorted(set(payload)-set(_FIELDS))}")
    for name in ("actor", "object", "deadline", "frequency", "threshold", "territorial_scope", "temporal_scope"):
        if payload[name] is not None and not isinstance(payload[name], str):
            raise ObligationValidationError(f"{name} must be a string or null")
    if payload["modality"] not in MODALITIES:
        raise ObligationValidationError("invalid modality")
    for name in ("action", "source_excerpt"):
        if not isinstance(payload[name], str) or not payload[name].strip():
            raise ObligationValidationError(f"{name} must be a nonempty string")
    for name in ("conditions", "exceptions"):
        if not isinstance(payload[name], list) or any(not isinstance(v, str) for v in payload[name]):
            raise ObligationValidationError(f"{name} must be an array of strings")
    start, end = payload["span_start"], payload["span_end"]
    if (start is None) != (end is None):
        raise ObligationValidationError("offsets must be both null or both integers")
    if start is not None and (type(start) is not int or type(end) is not int or start < 0 or end <= start):
        raise ObligationValidationError("invalid half-open span")
    if source_text is not None:
        if not isinstance(source_text, str):
            raise ObligationValidationError("source_text must be a string")
        if start is not None:
            if source_text[start:end] != payload["source_excerpt"]:
                raise ObligationValidationError("excerpt does not match source span")
        elif payload["source_excerpt"] not in source_text:
            raise ObligationValidationError("excerpt absent from source")
    return {k: (list(v) if isinstance(v, list) else v) for k, v in payload.items()}
