"""Tests for services.diagnosis.classifier — _parse_classification pure logic."""

import json

import pytest

from services.diagnosis.classifier import _parse_classification, _VALID_CATEGORIES


# ── _parse_classification ──


def test_parse_valid_json():
    raw = json.dumps({
        "category": "procedural",
        "confidence": 0.85,
        "evidence": "Used the wrong formula",
        "related_concept": "integration",
    })
    result = _parse_classification(raw)
    assert result["category"] == "procedural"
    assert result["confidence"] == 0.85
    assert result["evidence"] == "Used the wrong formula"
    assert result["related_concept"] == "integration"


def test_parse_json_surrounded_by_text():
    """JSON embedded in conversational text should still be extracted."""
    raw = 'Here is the classification:\n{"category": "computational", "confidence": 0.7, "evidence": "arithmetic error", "related_concept": "addition"}\nDone.'
    result = _parse_classification(raw)
    assert result["category"] == "computational"
    assert result["confidence"] == 0.7


def test_parse_no_json_returns_fallback():
    """No JSON braces should return conceptual fallback."""
    result = _parse_classification("I think it's a conceptual error because blah blah")
    assert result["category"] == "conceptual"
    assert result["confidence"] == 0.3
    assert result["related_concept"] == "unknown"


def test_parse_invalid_category_defaults_to_conceptual():
    raw = json.dumps({"category": "alien_mistake", "confidence": 0.5, "evidence": "dunno", "related_concept": "x"})
    result = _parse_classification(raw)
    assert result["category"] == "conceptual"


def test_parse_confidence_clamped():
    """Confidence outside 0-1 should be clamped."""
    raw = json.dumps({"category": "careless", "confidence": 2.5, "evidence": "typo", "related_concept": "spelling"})
    result = _parse_classification(raw)
    assert result["confidence"] == 1.0

    raw2 = json.dumps({"category": "careless", "confidence": -0.5, "evidence": "typo", "related_concept": "spelling"})
    result2 = _parse_classification(raw2)
    assert result2["confidence"] == 0.0


def test_parse_non_numeric_confidence_defaults():
    """Non-numeric confidence should default to 0.5."""
    raw = json.dumps({"category": "reading", "confidence": "high", "evidence": "misread", "related_concept": "units"})
    result = _parse_classification(raw)
    assert result["confidence"] == 0.5


def test_parse_malformed_json_returns_fallback():
    """Broken JSON should return fallback."""
    result = _parse_classification('{"category": "procedural", "confidence":')
    assert result["category"] == "conceptual"
    assert result["confidence"] == 0.3


def test_all_valid_categories_accepted():
    """Every defined category should be accepted."""
    for cat in _VALID_CATEGORIES:
        raw = json.dumps({"category": cat, "confidence": 0.5, "evidence": "test", "related_concept": "test"})
        result = _parse_classification(raw)
        assert result["category"] == cat
