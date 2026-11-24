# Quiz answer grading

The submit API continues to accept `user_answer` as a string. Existing text answers retain case-insensitive, outer-whitespace-insensitive exact matching. Numeric-looking text is not automatically treated as a number: identifiers, versions and significant leading-zero strings keep their existing semantics.

Non-coding questions must have a non-blank reference answer before a submission can be graded. A missing, empty or whitespace-only reference returns HTTP 422 (`validation_error`), with no correctness result, practice/wrong-answer record, progress/mastery update, analytics event or background diagnosis. The ownership check runs first. Existing clients treat this as a submission failure rather than recording an incorrect attempt. Coding questions retain their separate grader, which may work without a reference answer. This check does not establish that a non-blank reference is a sufficient rubric for subjective answers.

For a `short_answer` or `fill_blank` question whose author explicitly wants numerical equality, set `problem_metadata.answer_type` to `"number"` in the generated/imported question payload. The shared annotation pipeline preserves and validates this opt-in. Other question types cannot opt into this mode. Omitting the field, or specifying `"text"`, retains text matching.

```json
{
  "question_type": "fill_blank",
  "question": "Calculate one plus one.",
  "correct_answer": "2",
  "explanation": "One plus one equals two.",
  "problem_metadata": {"answer_type": "number"}
}
```

Numeric mode compares finite decimal values exactly, including scientific notation: `2`, `2.0`, `+02.000` and `2e0` are equal. Comparison uses decimal arithmetic, not binary floats or a tolerance. Numeric zero survives annotation. Each scalar is limited to 200 characters after stripping surrounding whitespace. Non-finite values, expressions/fractions, unit-bearing values, separators such as commas/underscores, and malformed numbers are rejected. An invalid reference is rejected during payload validation and never produces a correct result in submission grading.

This does not classify existing questions or backfill metadata. It adds no paid-model calls or subjective-answer grading. Existing select-all set grading and coding grading retain their separate paths. Questions requiring units, rounding tolerances or semantic evaluation need a separate explicit grading contract.

Coding submissions require a JSON boolean `is_correct` verdict from their grader. Provider setup/call failures and unparseable, missing, or non-boolean verdicts return HTTP 503 (`llm_unavailable`), with no correctness result or learning-record side effects. The client can retry the same answer; a later successful verdict creates one attempt. Strings such as `"false"` and numbers such as `0` are not coerced to booleans. A valid `false` verdict and an empty code submission still count as incorrect. The ownership check remains before grading. This does not alter historical attempts or the configured LLM provider, and adds no extra model calls.
