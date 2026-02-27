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
]
