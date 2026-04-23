# LLM Evaluation Harness

Regression test for LLM quality drift.

Runs a canned set of questions through the configured LLM router,
grades the answers, and produces a Markdown (and optionally JSON)
report. Intended for manual spot-checks and CI quality gates when you
switch model/provider.

## Run

```bash
# default: all three suites, threshold 0.70
python scripts/run_eval.py

# single suite, higher bar
python scripts/run_eval.py --suite quiz_30q --threshold 0.80

# persist a JSON report under tests/eval/reports/
python scripts/run_eval.py --output-json

# force a specific model for this run
python scripts/run_eval.py --model gpt-4o-mini
```

Exit code:

- `0` — overall score ≥ `--threshold`
- `1` — overall score below threshold

## Fixtures

| file | focus |
|---|---|
| `fixtures/quiz_30q.yaml` | 30 short-form Python / AI / softeng / behavioral |
| `fixtures/humaneval_subset.yaml` | 5 small coding tasks (structure-graded) |
| `fixtures/gsm8k_subset.yaml` | 5 arithmetic word problems |
| `fixtures/guardrails_smoke.yaml` | 10 Phase 7 questions — 5 in-corpus + 5 out-of-corpus |

Grade modes: `exact`, `contains`, `regex`, `judge`, `refusal`. See
`schemas/eval.py` for the full schema.

## Guardrails eval

Phase 7 ships a retrieval-required mode (`GUARDRAILS_STRICT=true`). The
`guardrails_smoke` suite regression-tests it — 5 in-corpus questions
should be answered grounded, 5 out-of-corpus questions should be refused
with the canned `REFUSAL_TEMPLATE`.

```bash
# Run guardrails suite in strict mode (sets GUARDRAILS_STRICT=true for
# the duration of the process).
python scripts/run_eval.py --strict --suite guardrails_smoke
```

The `refusal` grade mode matches whenever the answer begins with
`"I don't have this in your course…"` (case-insensitive).

## Adding questions

Append under `questions:` in the relevant YAML. Keep `expected`
tolerant for regex/contains grading — we're detecting drift, not
measuring benchmark accuracy.

## Cost

A full run against OpenAI `gpt-4o-mini` costs roughly $0.05 per
execution (40 short prompts). Groq/local providers are effectively
free.
