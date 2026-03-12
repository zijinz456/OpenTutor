# apps/api/services/lector.py

import datetime
from typing import List, Dict
from sqlalchemy.orm import Session
from apps.api.models import Concept, ReviewSession, ReviewRating
from apps.api.config import LECTOR_FACTOR_WEIGHTS

class LectorService:
    def __init__(self, db: Session):
        self.db = db

    def get_concepts_by_priority(self) -> List[Concept]:
        # Fetch concepts with priority scoring
        concepts = self.db.query(Concept).all()
        concepts.sort(key=lambda c: self.calculate_priority(c))
        return concepts

    def calculate_priority(self, concept: Concept) -> float:
        # Calculate priority based on various factors
        low_mastery = 0.5 if concept.mastery < 0.5 else 0
        never_practiced = 0.3 if concept.last_reviewed is None else 0
        time_decay = 0.3 * (datetime.datetime.now() - concept.last_reviewed).days if concept.last_reviewed else 0
        prerequisite = 0.2 * self.calculate_prerequisite_factor(concept)
        confusion = 0.1 * self.calculate_confusion_factor(concept)
        return (
            low_mastery * LECTOR_FACTOR_WEIGHTS['low_mastery'] +
            never_practiced * LECTOR_FACTOR_WEIGHTS['never_practiced'] +
            time_decay * LECTOR_FACTOR_WEIGHTS['time_decay'] +
            prerequisite * LECTOR_FACTOR_WEIGHTS['prerequisite'] +
            confusion * LECTOR_FACTOR_WEIGHTS['confusion']
        )

    def calculate_prerequisite_factor(self, concept: Concept) -> float:
        # Calculate prerequisite factor
        if not concept.prerequisites:
            return 1
        mastered_prerequisites = sum(1 for p in concept.prerequisites if p.mastery >= 0.8)
        return mastered_prerequisites / len(concept.prerequisites)

    def calculate_confusion_factor(self, concept: Concept) -> float:
        # Calculate confusion factor
        if not concept.confusion_pairs:
            return 0
        return sum(1 for p in concept.confusion_pairs if p.mastery < 0.5) / len(concept.confusion_pairs)

    def schedule_proactive_reviews(self):
        # Schedule proactive reviews
        concepts = self.get_concepts_by_priority()
        for concept in concepts:
            if concept.mastery < 0.8:
                self.create_review_session(concept)

    def create_review_session(self, concept: Concept):
        # Create a review session for a concept
        session = ReviewSession(concept_id=concept.id, scheduled_at=datetime.datetime.now())
        self.db.add(session)
        self.db.commit()

    def cluster_sessions(self, sessions: List[ReviewSession]) -> Dict[str, List[ReviewSession]]:
        # Cluster review sessions by related concepts
        clusters = {}
        for session in sessions:
            concept = self.db.query(Concept).filter(Concept.id == session.concept_id).first()
            if concept.cluster_id not in clusters:
                clusters[concept.cluster_id] = []
            clusters[concept.cluster_id].append(session)
        return clusters

    def apply_consolidation_bonuses(self, sessions: List[ReviewSession]):
        # Apply consolidation bonuses for mastered prerequisite groups
        clusters = self.cluster_sessions(sessions)
        for cluster_id, cluster_sessions in clusters.items():
            if self.is_cluster_mastered(cluster_id):
                for session in cluster_sessions:
                    session.bonus += 10  # Example bonus value

    def is_cluster_mastered(self, cluster_id: int) -> bool:
        # Check if a cluster is mastered
        concepts = self.db.query(Concept).filter(Concept.cluster_id == cluster_id).all()
        return all(c.mastery >= 0.8 for c in concepts)