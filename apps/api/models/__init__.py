"""SQLAlchemy ORM models — import all to register with Base.metadata."""

from models.user import User
from models.course import Course
from models.content import CourseContentTree
from models.preference import UserPreference, PreferenceSignal
from models.practice import PracticeProblem, PracticeResult
from models.memory import ConversationMemory
from models.ingestion import IngestionJob, StudySession, Assignment, WrongAnswer
from models.progress import LearningProgress, LearningTemplate
from models.scrape import ScrapeSource, AuthSession
from models.chat_session import ChatSession
from models.chat_message import ChatMessageLog
from models.generated_asset import GeneratedAsset
from models.study_plan import StudyPlan
from models.study_goal import StudyGoal
from models.agent_task import AgentTask
from models.agenda_run import AgendaRun
from models.agent_kv import AgentKV
from models.mastery_snapshot import MasterySnapshot
from models.integration_credential import IntegrationCredential
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from models.notification import Notification
from models.cognitive_baseline import CognitiveBaseline
from models.usage_event import UsageEvent
from models.intervention_outcome import InterventionOutcome

__all__ = [
    "User",
    "Course",
    "CourseContentTree",
    "UserPreference",
    "PreferenceSignal",
    "PracticeProblem",
    "PracticeResult",
    "ConversationMemory",
    "IngestionJob",
    "StudySession",
    "Assignment",
    "WrongAnswer",
    "LearningProgress",
    "LearningTemplate",
    "ScrapeSource",
    "AuthSession",
    "ChatSession",
    "ChatMessageLog",
    "GeneratedAsset",
    "StudyPlan",
    "StudyGoal",
    "AgentTask",
    "AgendaRun",
    "AgentKV",
    "MasterySnapshot",
    "IntegrationCredential",
    "KnowledgeNode",
    "KnowledgeEdge",
    "ConceptMastery",
    "Notification",
    "CognitiveBaseline",
    "UsageEvent",
    "InterventionOutcome",
]
