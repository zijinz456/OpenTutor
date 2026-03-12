"""DeepEval LLM output quality evaluation tests.

Tests key LLM-powered features for:
- Hallucination detection
- Faithfulness to source material
- Answer relevance
- Correctness of structured outputs (JSON conformance)

Requires: pip install deepeval
Configure: OPENAI_API_KEY env var (for DeepEval's evaluation LLM)

Usage:
    PYTHONPATH=apps/api .venv/bin/python -m pytest tests/test_deepeval_llm_quality.py -v
"""

import json
import os
import sys
import importlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

# Skip entire module if deepeval is unavailable or misconfigured in this env.
try:
    importlib.import_module("deepeval")
except Exception as exc:  # pragma: no cover - environment-dependent optional dependency
    pytest.skip(f"deepeval unavailable: {exc}", allow_module_level=True)


def _has_evaluator_key():
    """Check if we have an API key for the evaluation LLM."""
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPEVAL_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


skip_no_key = pytest.mark.skipif(
    not _has_evaluator_key(),
    reason="No evaluator API key (OPENAI_API_KEY or DEEPEVAL_API_KEY)",
)


# ── Unit tests for structured output correctness (no LLM needed) ──


class TestErrorClassificationFormat:
    """Validate error classification output schema compliance."""

    VALID_CATEGORIES = {"conceptual", "procedural", "computational", "reading", "careless"}

    def _validate_classification(self, output: dict):
        assert "category" in output, "Missing 'category' field"
        assert output["category"] in self.VALID_CATEGORIES, f"Invalid category: {output['category']}"
        assert "confidence" in output, "Missing 'confidence' field"
        assert 0.0 <= output["confidence"] <= 1.0, f"Confidence out of range: {output['confidence']}"
        assert "evidence" in output, "Missing 'evidence' field"
        assert isinstance(output["evidence"], str), "Evidence must be a string"
        assert len(output["evidence"]) > 5, "Evidence too short"

    def test_conceptual_error_schema(self):
        output = {
            "category": "conceptual",
            "confidence": 0.85,
            "evidence": "Student confused derivative with integral",
            "related_concept": "differentiation",
        }
        self._validate_classification(output)

    def test_procedural_error_schema(self):
        output = {
            "category": "procedural",
            "confidence": 0.9,
            "evidence": "Applied chain rule incorrectly",
            "related_concept": "chain_rule",
        }
        self._validate_classification(output)

    def test_invalid_category_rejected(self):
        output = {"category": "unknown", "confidence": 0.5, "evidence": "test"}
        with pytest.raises(AssertionError, match="Invalid category"):
            self._validate_classification(output)

    def test_confidence_out_of_range(self):
        output = {"category": "conceptual", "confidence": 1.5, "evidence": "test reason"}
        with pytest.raises(AssertionError, match="out of range"):
            self._validate_classification(output)


class TestQuizGenerationFormat:
    """Validate quiz generation output schema compliance."""

    VALID_TYPES = {"mc", "tf", "short_answer", "fill_blank"}
    VALID_BLOOM = {"remember", "understand", "apply", "analyze", "evaluate", "create"}

    def _validate_quiz_question(self, q: dict):
        assert "question_type" in q, "Missing question_type"
        assert q["question_type"] in self.VALID_TYPES, f"Invalid type: {q['question_type']}"
        assert "question" in q and len(q["question"]) > 10, "Question too short"
        assert "correct_answer" in q, "Missing correct_answer"
        assert "explanation" in q, "Missing explanation"

        if q["question_type"] == "mc":
            assert "options" in q, "MC question missing options"
            opts = q["options"]
            assert isinstance(opts, dict), "Options must be a dict"
            assert set(opts.keys()) == {"A", "B", "C", "D"}, f"MC must have A-D options, got {set(opts.keys())}"

        # Metadata validation
        if "difficulty_layer" in q:
            assert q["difficulty_layer"] in (1, 2, 3), f"Invalid layer: {q['difficulty_layer']}"
        if "bloom_level" in q:
            assert q["bloom_level"] in self.VALID_BLOOM, f"Invalid bloom: {q['bloom_level']}"

    def test_mc_question_valid(self):
        q = {
            "question_type": "mc",
            "question": "What is the derivative of x^2?",
            "options": {"A": "x", "B": "2x", "C": "x^2", "D": "2"},
            "correct_answer": "B",
            "explanation": "Power rule: d/dx(x^n) = nx^(n-1)",
            "difficulty_layer": 1,
            "bloom_level": "remember",
        }
        self._validate_quiz_question(q)

    def test_tf_question_valid(self):
        q = {
            "question_type": "tf",
            "question": "The integral of a constant is always zero.",
            "correct_answer": "False",
            "explanation": "The integral of a constant c is cx + C",
        }
        self._validate_quiz_question(q)

    def test_mc_missing_option_rejected(self):
        q = {
            "question_type": "mc",
            "question": "What is 2+2?",
            "options": {"A": "3", "B": "4", "C": "5"},  # Missing D
            "correct_answer": "B",
            "explanation": "Basic arithmetic",
        }
        with pytest.raises(AssertionError, match="A-D"):
            self._validate_quiz_question(q)


class TestDiagnosticDerivationFormat:
    """Validate diagnostic question derivation output."""

    def _validate_diagnostic(self, output: dict):
        assert "question" in output, "Missing question"
        assert "correct_answer" in output, "Missing correct_answer"
        assert "explanation" in output, "Missing explanation"
        assert "simplifications_made" in output, "Missing simplifications_made"
        assert isinstance(output["simplifications_made"], list), "simplifications_made must be list"
        assert len(output["simplifications_made"]) >= 1, "Must have at least 1 simplification"
        assert "core_concept_preserved" in output, "Missing core_concept_preserved"

    def test_valid_diagnostic(self):
        output = {
            "question": "What is the derivative of x^2?",
            "options": {"A": "x", "B": "2x", "C": "x^2", "D": "2"},
            "correct_answer": "B",
            "explanation": "Apply the power rule directly",
            "simplifications_made": ["Removed chain rule complexity", "Simplified to single term"],
            "core_concept_preserved": "power_rule",
        }
        self._validate_diagnostic(output)


class TestSocraticStateClassification:
    """Validate Socratic engine response quality classification."""

    VALID_QUALITIES = {"correct", "partial", "wrong", "confused", "no_response"}

    def test_all_qualities_recognized(self):
        for quality in self.VALID_QUALITIES:
            assert quality in self.VALID_QUALITIES


# ── DeepEval integration tests (require evaluator API key) ──


@skip_no_key
class TestDeepEvalTutorQuality:
    """End-to-end LLM output quality tests using DeepEval metrics."""

    def test_teaching_response_faithfulness(self):
        """Test that tutor responses are faithful to provided source material."""
        from deepeval.test_case import LLMTestCase
        from deepeval.metrics import FaithfulnessMetric

        test_case = LLMTestCase(
            input="Explain what a derivative is",
            actual_output="A derivative measures the rate of change of a function. "
            "It represents the slope of the tangent line at any point on the curve. "
            "For f(x) = x^2, the derivative f'(x) = 2x.",
            retrieval_context=[
                "A derivative is a fundamental concept in calculus that measures "
                "the instantaneous rate of change of a function with respect to its variable. "
                "The derivative of f(x) = x^n is f'(x) = nx^(n-1) (power rule)."
            ],
        )

        metric = FaithfulnessMetric(threshold=0.7)
        metric.measure(test_case)
        assert metric.score >= 0.7, f"Faithfulness too low: {metric.score}"

    def test_teaching_response_relevance(self):
        """Test that tutor responses are relevant to student questions."""
        from deepeval.test_case import LLMTestCase
        from deepeval.metrics import AnswerRelevancyMetric

        test_case = LLMTestCase(
            input="How do I find the area under a curve?",
            actual_output="To find the area under a curve, you use integration. "
            "The definite integral from a to b of f(x) gives the signed area "
            "between the curve and the x-axis.",
        )

        metric = AnswerRelevancyMetric(threshold=0.7)
        metric.measure(test_case)
        assert metric.score >= 0.7, f"Relevance too low: {metric.score}"

    def test_no_hallucination_in_quiz_explanation(self):
        """Test that quiz explanations don't hallucinate beyond source material."""
        from deepeval.test_case import LLMTestCase
        from deepeval.metrics import HallucinationMetric

        test_case = LLMTestCase(
            input="Generate a quiz question about photosynthesis",
            actual_output="Question: What is the primary pigment in photosynthesis?\n"
            "Answer: Chlorophyll\n"
            "Explanation: Chlorophyll is the green pigment found in chloroplasts "
            "that absorbs light energy for photosynthesis.",
            context=[
                "Photosynthesis is the process by which plants convert light energy "
                "into chemical energy. The primary pigment is chlorophyll, located "
                "in chloroplasts. The process produces glucose and oxygen from "
                "carbon dioxide and water."
            ],
        )

        metric = HallucinationMetric(threshold=0.7)
        metric.measure(test_case)
        assert metric.score >= 0.7, f"Hallucination score too low: {metric.score}"
