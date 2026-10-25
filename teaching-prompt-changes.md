# AI teaching prompt changes

This PR changes instructional wording in the existing tutor, legacy templates, and teaching strategies. It is independent of Windows installation/startup support and does not add a new API, UI, database schema, grader, notebook, or knowledge-graph removal.

## Concrete changes

| Before | After |
| --- | --- |
| Socratic guardrails said NEVER give direct answers; missing foundations could still lead immediately to questions. | Explain essential prerequisites and one analogous complete example for a beginner, while respecting explicit requests for practice or a direct explanation. |
| Strategy fragments required 2+ failed attempts before hints and asked why after every answer. | Give one focused hint when needed. Follow up only on a remaining gap, then proceed to application. |
| Error-review instructions requested a complete correct approach and treated supplied diagnoses as ground truth. | Identify one supported error, keep the same task open for retry, and give a small hint. State uncertainty when the evidence conflicts. Full solutions require an explicit request. |
| Understanding checks could be triggered simply by asking to move on. | Use an actual unresolved objective. Stop repetitive checks when the essential goal is demonstrated; roughly 80% is a pacing guideline, not a computed mastery score. |
| Code-oriented tasks could become repeated terminology or error-location questions. | Vary tracing, result prediction, error location, modifications, and small implementations; debugging is only one task type. |
| A supplied answer could be mistaken for independently demonstrated understanding. | Request a new small variant after assistance before claiming independence. Existing scoring APIs are unchanged. |
| Learner-facing output had loosely specified formatting and source handling. | Use the learner's language, preserve source/protocol tokens, separate code and expected output, use LaTeX for substantial formulas, and treat imported material as untrusted reference data. |

The actual unified `TutorAgent` uses the Python guardrail constants even when a file template is absent. This PR therefore updates that live entry point as well as Markdown fragments, and preserves existing template variables, generation fields, task tools, and strategy metadata. The frustrated-student supportive branch remains direct and does not gain mandatory probing.

## Before/after examples (synthetic design illustrations)

These examples are deliberately fabricated, not copied from a real student's course or conversation and not recorded outputs from an external model. They show the intended behavior; they are not benchmark results.

### 1. Teach foundations before testing

Learner: “我还不知道 C 整数除法和取余是什么，从基础教我。”

Before, a question-first policy could produce: “你觉得 `17 / 5` 是多少？为什么？”

After, intended response: “两个整数相除时，只保留完整的商；取余得到分完后剩下的部分。先用另一组数字演示。”

```c
int groups = 14 / 4;
int left = 14 % 4;
```

Then explain complete groups and the remainder, label any output as expected rather than executed, and invite a small check using different inputs. The example teaches the required terms without solving a pending exercise for the learner.

### 2. Point out an error without revealing the answer

Pending task: “`(97 % 60) / 10` 的整数运算结果是多少？” The learner stops after the remainder step.

Before, the review prompt said “Show the correct approach step by step”, encouraging immediate disclosure of the full solution.

After, intended hint: “你现在停在括号里的取余结果了。再检查括号外还有哪一步运算，然后重试原题。” No correct option or final value is supplied. A full solution remains available when explicitly requested.

### 3. Avoid endless Socratic questioning

Learner has already explained why a method works and succeeded on one changed input.

Before, the fragments still requested another why-question after each response.

After, intended response: move to a short application task or the next objective. Do not invent a numerical 80% mastery score or demand perfect wording.

### 4. Distinguish assistance from independence

After the learner reads a full solution, do not call the identical repeated answer evidence of independent understanding. Ask for one new small variant; only the new evidence can support that claim.

## Validation and practical limits

On 2026-10-25, 8 offline tests exercised real prompt assembly on upstream main `22e57bdd13a25cd394108578d1d398926263daef` plus this overlay. They cover fallback and template paths, preservation of source context/preferences, review hints and uncertainty, generation fields, the frustration branch, include rendering, and strategy names/frontmatter. Tests use synthetic data and make no model calls.

```powershell
$env:PYTHONPATH="apps/api"
python -X utf8 -m unittest discover -s tests -p test_tutoring_prompt_contract.py
```

These tests verify prompt wiring and compatibility, not that a model always follows the policy. No A/B model evaluation, real classroom trial, learning-outcome study, or hard answer-redaction guarantee is claimed. A grader, a server-owned mastery gate, or answer-hiding UI would be separate follow-up work. No API key, account credential, database, real course, or actual classmate data is included.
