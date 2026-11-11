"""Explicit numeric semantics are preserved and validated at ingestion."""

import pytest

from services.practice.annotation import normalize_problem_annotation, validate_question_payload


def payload(reference="2", question_type="fill_blank", answer_type="number"):
    return {"question_type": question_type, "question": "Calculate one plus one.",
            "correct_answer": reference, "explanation": "One plus one equals two.",
            "difficulty_layer": 1, "problem_metadata": {"answer_type": answer_type}}


@pytest.mark.parametrize("reference", ["2", "0", 0])
def test_numeric_metadata_and_zero_survive_normalization(reference):
    normalized = normalize_problem_annotation(payload(reference), title="Arithmetic")
    assert normalized["problem_metadata"]["answer_type"] == "number"
    assert normalized["correct_answer"] == str(reference)


@pytest.mark.parametrize("reference", ["NaN", "Infinity", "1/2", "2 kg", "", "1" * 201])
def test_invalid_numeric_reference_is_rejected(reference):
    result = validate_question_payload(payload(reference), title="Arithmetic")
    assert not result.is_valid
    assert any("numeric" in error for error in result.errors)


def test_numeric_metadata_is_not_accepted_for_subjective_questions():
    result = validate_question_payload(payload(question_type="free_response"), title="Arithmetic")
    assert not result.is_valid
    assert any("answer_type" in error for error in result.errors)


def test_unknown_answer_type_is_rejected_instead_of_guessed():
    result = validate_question_payload(payload(answer_type="numeric"), title="Arithmetic")
    assert not result.is_valid
    assert any("answer_type" in error for error in result.errors)


@pytest.mark.parametrize("answer,reference,expected", [
    ("0.0", "0", True), ("-0", "0", True), (".5", "5e-1", True),
    ("-2e3", "-2000", True), ("1.00", "1e0", True),
    ("9007199254740992", "9007199254740993", False),
    ("2.0000000000000000001", "2", False),
    ("1/2", "0.5", False), ("2 kg", "2", False),
    ("1,000", "1000", False), ("1_000", "1000", False),
    ("", "0", False), ("NaN", "NaN", False), ("Infinity", "Infinity", False),
    ("1e999999999999999999999999999", "1", False),
    ("1" * 201, "1" * 201, False),
])
def test_numeric_comparison_is_exact_finite_and_bounded(answer, reference, expected):
    from services.practice.answers import grade_text_answer
    assert grade_text_answer(answer, reference, numeric=True) is expected


@pytest.mark.parametrize("answer,reference,expected", [
    (" PARIS ", "paris", True), ("0012", "12", False), ("2.0", "2", False),
])
def test_text_comparison_does_not_infer_numeric_semantics(answer, reference, expected):
    from services.practice.answers import grade_text_answer
    assert grade_text_answer(answer, reference) is expected
