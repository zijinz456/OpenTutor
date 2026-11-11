# Quiz answer grading

The submit API continues to accept `user_answer` as a string. Existing text answers retain case-insensitive, outer-whitespace-insensitive exact matching. Numeric-looking text is not automatically treated as a number: identifiers, versions and significant leading-zero strings keep their existing semantics.

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
