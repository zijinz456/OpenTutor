"""Screenshot-to-Drill services (MASTER §14 Phase 4).

Modules:
- ``vision_extractor`` (T1) — one vision-LLM call per uploaded
  screenshot → 0 to 5 :class:`~schemas.curriculum.CardCandidate`
  entries. Never raises; applies a post-LLM PII regex filter to drop
  cards containing credentials / tokens / emails / passwords.
"""
