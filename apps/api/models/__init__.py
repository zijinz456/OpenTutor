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
from models.scene import Scene, SceneSnapshot, SceneSwitchLog
from models.knowledge_graph import KnowledgePoint
from models.chat_session import ChatSession
from models.chat_message import ChatMessageLog
from models.generated_asset import GeneratedAsset
from models.study_plan import StudyPlan

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
    "Scene",
    "SceneSnapshot",
    "SceneSwitchLog",
    "KnowledgePoint",
    "ChatSession",
    "ChatMessageLog",
    "GeneratedAsset",
    "StudyPlan",
]
