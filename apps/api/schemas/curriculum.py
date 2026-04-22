"""Pydantic schemas for the URL-auto-curriculum feature (§14.5 v2.1).

Two LLM contracts live here:

1. ``Syllabus`` — produced by ``services.curriculum.syllabus_builder``.
   One call per URL ingest. Maps scraped document tree to a topic roadmap
   of 3-15 ``SyllabusNode`` entries plus a topo-sorted ``suggested_path``.

2. ``CardBatch`` — produced by ``services.curriculum.card_spawner``.
   One call per tutor chat turn. Emits ≤3 spaced-repetition flashcard
   candidates grounded in the response + retrieved chunks.

Schemas mirror the plan doc (``plan/url_autocurriculum_v2.1.md`` §LLM
contracts). Both are consumed by LLMs returning structured JSON and by
downstream DB writers.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


# ── syllabus_builder — one call per URL ingest ───────────────


class SyllabusNode(BaseModel):
    """Single topic in the generated roadmap.

    ``slug`` is the stable identifier used in ``depends_on`` / ``suggested_path``
    cross-references. It must match the kebab-case pattern to stay readable in
    URLs and JSONB metadata.
    """

    slug: str = Field(pattern=r"^[a-z0-9-]{3,60}$")
    topic: str = Field(min_length=1, max_length=80)
    blurb: str = Field(min_length=1, max_length=200)
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("depends_on")
    @classmethod
    def _validate_depends_on_slugs(cls, v: list[str]) -> list[str]:
        """Each element of ``depends_on`` must itself be a valid slug."""
        import re

        pattern = re.compile(r"^[a-z0-9-]{3,60}$")
        for item in v:
            if not pattern.match(item):
                raise ValueError(
                    f"depends_on entry {item!r} is not a valid kebab-case slug"
                )
        return v


class Syllabus(BaseModel):
    """LLM-generated roadmap for a single ingested URL.

    ``suggested_path`` must be a valid topological sort: every slug in the
    path must exist in ``nodes``, every node must appear exactly once, and
    for every node the path index of each of its ``depends_on`` slugs must
    come strictly before the node itself.
    """

    nodes: list[SyllabusNode] = Field(min_length=3, max_length=15)
    suggested_path: list[str]

    @model_validator(mode="after")
    def _validate_path_is_valid_topo_sort(self) -> Syllabus:
        slugs = [n.slug for n in self.nodes]
        slug_set = set(slugs)

        # 1. Unique slugs within nodes
        if len(slug_set) != len(slugs):
            raise ValueError("nodes contain duplicate slugs")

        # 2. suggested_path covers the exact same set, each exactly once
        if len(self.suggested_path) != len(slugs):
            raise ValueError("suggested_path length must equal number of nodes")
        if set(self.suggested_path) != slug_set:
            raise ValueError("suggested_path must list every node slug exactly once")
        if len(set(self.suggested_path)) != len(self.suggested_path):
            raise ValueError("suggested_path contains duplicate entries")

        # 3. depends_on references must point at known nodes (no dangling)
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in slug_set:
                    raise ValueError(
                        f"node {node.slug!r} depends_on unknown slug {dep!r}"
                    )
                if dep == node.slug:
                    raise ValueError(f"node {node.slug!r} cannot depend on itself")

        # 4. Topological order: for each node, every dependency must appear
        #    earlier in suggested_path than the node itself.
        position = {slug: idx for idx, slug in enumerate(self.suggested_path)}
        node_by_slug = {n.slug: n for n in self.nodes}
        for slug in self.suggested_path:
            node = node_by_slug[slug]
            for dep in node.depends_on:
                if position[dep] >= position[slug]:
                    raise ValueError(
                        f"suggested_path is not a valid topo-sort: "
                        f"{dep!r} must come before {slug!r}"
                    )

        return self


# ── card_spawner — one call per chat turn ────────────────────


class CardCandidate(BaseModel):
    """Single flashcard candidate surfaced to the learner after a chat turn."""

    front: str = Field(min_length=1, max_length=200)
    back: str = Field(min_length=1, max_length=500)
    concept_slug: str | None = None


class CardBatch(BaseModel):
    """Batch of card candidates (≤3) emitted after a single tutor turn."""

    cards: list[CardCandidate] = Field(max_length=3)


# ── /sessions/{sid}/messages/{mid}/card-candidates response ──


class CardCandidatesResponse(BaseModel):
    """Response body for ``GET /sessions/{sid}/messages/{mid}/card-candidates``.

    Two-field envelope so the frontend can distinguish:

    * ``cards=[card, card, ...]`` — spawner ran and returned candidates.
    * ``cards=[]`` (no ``reason``) — spawner ran and returned zero.
      The learner should see *no* toast; the tutor turn simply wasn't
      card-worthy.
    * ``cards=[]``, ``reason="no_candidates"`` — cache miss + wait
      timeout. Either the spawner was never triggered (non-teaching
      intent), still running past the timeout, or the cached entry
      already expired. Semantically indistinguishable from "zero cards"
      for the frontend but a separate branch for debugging / telemetry.

    We intentionally keep the schema flat rather than introducing a
    status enum — a frontend that just renders ``response.cards`` works
    correctly in every branch.
    """

    cards: list[CardCandidate] = Field(default_factory=list)
    reason: str | None = None


# ── /courses/{id}/flashcards/save-candidates req/resp ────────


class SaveCandidatesRequest(BaseModel):
    """Request body for ``POST /api/courses/{course_id}/flashcards/save-candidates``.

    A batch of 1–N :class:`CardCandidate` rows the user picked from the
    tutor-turn toast (§14.5 T6). Empty batches are rejected by the
    endpoint with HTTP 400 — we don't silently "save zero cards".
    """

    candidates: list[CardCandidate] = Field(min_length=1)


class SaveCandidatesResponse(BaseModel):
    """Response body for the save-candidates endpoint.

    Fields:
        saved_problem_ids: one ``PracticeProblem.id`` per saved card, in
            the same order as the input ``candidates`` list.
        asset_id: the ``GeneratedAsset.id`` holding the batch in its
            ``content['cards']`` for the flashcard-due UI. One row per
            save call; cards inside it are cross-linked to the
            ``saved_problem_ids`` via ``cards[i]['practice_problem_id']``.
        count: ``len(saved_problem_ids)`` — equals ``len(request.candidates)``.
        warnings: human-readable strings, one per unmatched
            ``concept_slug`` (slug that did not resolve to any
            ``KnowledgeNode`` in this course). The corresponding card is
            still persisted, just with ``content_node_id=NULL``.
    """

    saved_problem_ids: list[uuid.UUID]
    asset_id: uuid.UUID
    count: int
    warnings: list[str] = Field(default_factory=list)


# ── /courses/{id}/roadmap response row ───────────────────────


class RoadmapEntry(BaseModel):
    """One entry of the course roadmap list returned by
    ``GET /api/courses/{course_id}/roadmap``.

    The endpoint joins :class:`models.knowledge_graph.KnowledgeNode` (rows
    written by T2's ``persist_syllabus``) with the current user's
    :class:`models.knowledge_graph.ConceptMastery` (LEFT JOIN — fresh
    nodes have no mastery row yet → ``mastery_score`` stays at its default
    0.0). Entries are returned in the order encoded in
    ``course.metadata_['roadmap']['path']``; ``position`` is that zero-based
    path index, i.e. the learner's recommended study order.

    Fields:
        node_id: ``KnowledgeNode.id``.
        slug: stable kebab-case identifier from
            ``KnowledgeNode.metadata_['slug']`` (written by T2).
        topic: human-readable topic label (``KnowledgeNode.name``).
        blurb: short description shown beside the topic
            (``KnowledgeNode.description``); ``None`` if absent.
        mastery_score: ``ConceptMastery.mastery_score`` for the current user
            on this node, in ``[0.0, 1.0]``. Defaults to ``0.0`` when no
            mastery row exists yet.
        position: zero-based index of this entry in the roadmap path.
    """

    node_id: uuid.UUID
    slug: str
    topic: str
    blurb: str | None = None
    mastery_score: float = 0.0
    position: int
