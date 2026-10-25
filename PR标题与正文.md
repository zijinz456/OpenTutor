# fix(tutor): teach foundations and give targeted hints before solutions

The existing unconditional question-first/never-answer rules can make beginners guess before learning prerequisites. Error-review instructions can disclose the whole solution, while repeated why-questions continue after understanding is clear.

This PR updates the real TutorAgent prompt constants, legacy templates and teaching strategy fragments. It explains foundations and an analogous example first, provides one supported error and small hint with same-task retry, uses purposeful Socratic/Feynman follow-ups, and moves to application when the essential goal is demonstrated. Assisted completion calls for a fresh variant before claiming independence.

## Before/after examples — synthetic illustrations

- Learner: “我还不知道 C 整数除法和取余是什么，从基础教我。” Before: the policy could ask “17 / 5 是多少？为什么？” After: explain complete groups and remainders using another input (14 / 4 and 14 % 4), then check understanding.
- Learner stops at the remainder in (97 % 60) / 10. Before: review rules request the complete correct approach. After: “你现在停在括号里的取余结果了。再检查括号外还有哪一步运算，然后重试原题。” No correct option or final value appears in this intended hint.
- After a reason and one changed-input task are demonstrated, proceed to application instead of repeating the same why-question.

These are fabricated design examples, not real student records or measured model outputs. More mappings and examples: [Teaching prompt guide](docs/guides/teaching-prompt-changes.md).

## Validation and limits

8 offline real-prompt-assembly checks passed: template/fallback paths, source/preferences, hints/uncertainty, generation fields, frustration branch, includes and strategy metadata. No model calls were made.

No Windows code, new UI/API, schema migration, grading implementation or hard mastery gate is added. “Roughly 80%” is a pacing guideline rather than a new numerical mastery score. Prompt wiring checks do not prove model obedience, answer-redaction guarantees or learning-outcome improvement. No API key, credential, database, real course or classmate data is submitted.

Base: upstream main `22e57bdd13a25cd394108578d1d398926263daef`. Independent of the Windows PR.
