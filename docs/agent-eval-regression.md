# Agent Eval And Regression

OpenTutor Zenus now exposes a bundled regression benchmark at `POST /api/eval/regression`.

`strict` mode is supported via request payload:

```json
{
  "strict": true
}
```

When `strict=true`, skipped `retrieval` or `recovery` suites are treated as failures.

What it checks by default:

- routing accuracy against golden intent cases
- retrieval benchmark when `course_id` and `retrieval_queries` are supplied
- response-quality benchmark when `response_cases` are supplied
- recovery benchmark when DB-backed checks are available

Minimal example:

```bash
curl -X POST http://localhost:8000/api/eval/regression \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Optional retrieval run:

```json
{
  "course_id": "00000000-0000-0000-0000-000000000000",
  "retrieval_queries": [
    {"query": "binary search invariant", "keywords": ["binary search", "invariant"]}
  ]
}
```

Optional response-quality run:

```json
{
  "response_cases": [
    {
      "question": "What is gradient descent?",
      "response": "Gradient descent iteratively updates parameters in the direction that reduces loss.",
      "context": "Gradient descent is an optimisation method that follows the negative gradient."
    }
  ]
}
```

Thresholds are currently enforced in `apps/api/services/evaluation/benchmark_runner.py`.

CI now enforces two gates:

- an offline benchmark gate in `.github/workflows/ci.yml`
- an API-level strict regression gate against `POST /api/eval/regression` with fixture payload
