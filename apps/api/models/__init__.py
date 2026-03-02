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
from models.study_goal import StudyGoal
from models.agent_task import AgentTask
from models.notification import Notification
from models.notification_settings import NotificationSettings
from models.push_subscription import PushSubscription
from models.notification_delivery import NotificationDelivery
from models.study_habit import StudyHabitLog
from models.experiment import Experiment, ExperimentAssignment, ExperimentEvent
from models.channel_binding import ChannelBinding
from models.audit_log import AuditLog
from models.agent_kv import AgentKV
from models.tool_call_event import ToolCallEvent

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
    "StudyGoal",
    "AgentTask",
    "Notification",
    "NotificationSettings",
    "PushSubscription",
    "NotificationDelivery",
    "StudyHabitLog",
    "Experiment",
    "ExperimentAssignment",
    "ExperimentEvent",
    "ChannelBinding",
    "AuditLog",
    "AgentKV",
    "ToolCallEvent",
]
