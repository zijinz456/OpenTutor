/**
 * Barrel re-export for the modular API layer.
 *
 * Every public type and function that was previously exported from
 * the monolithic api.ts is re-exported here so that all existing
 * `import { ... } from "@/lib/api"` statements continue to work.
 */

export type { JsonObject, NullableDateTime } from "./client";

export {
  listCourseOverview,
  getHealthStatus,
  createCourse,
  updateCourse,
  deleteCourse,
  getContentTree,
  restructureNotes,
  saveGeneratedNotes,
  listGeneratedNoteBatches,
  getAiNoteForNode,
  uploadFile,
  scrapeUrl,
  getFileUrl,
  listAuthSessions,
  canvasBrowserLogin,
  updateCourseLayout,
} from "./courses";

export type {
  CourseWorkspaceFeatures,
  CourseAutoScrapeSettings,
  CourseMetadata,
  Course,
  CourseOverviewCard,
  HealthStatus,
  ContentNode,
  RestructuredNotes,
  AuthSessionSummary,
  AiNoteForNode,
} from "./courses";

export {
  streamChat,
  listChatSessions,
  getChatSessionMessages,
} from "./chat";

export type {
  ChatAction,
  ChatHistoryMessage,
  ChatSessionSummary,
  ChatProvenance,
  ChatMessageMetadata,
  ClarifyOption,
  PlanProgressEvent,
  ImageAttachment,
} from "./chat";

export {
  listWrongAnswers,
  retryWrongAnswer,
  deriveQuestion,
  diagnoseWrongAnswer,
  getWrongAnswerStats,
  extractQuiz,
  listProblems,
  listGeneratedQuizBatches,
  submitAnswer,
  generateFlashcards,
  saveGeneratedFlashcards,
  listGeneratedFlashcardBatches,
  reviewFlashcard,
  getDueFlashcards,
  getWrongAnswerReview,
} from "./practice";

export type {
  DerivedQuestionResult,
  WrongAnswerStats,
  WrongAnswer,
  QuizProblem,
  GeneratedQuizBatchSummary,
  GeneratedAssetBatchSummary,
  AnswerResult,
  PrerequisiteGap,
  DueFlashcardsResult,
  Flashcard,
} from "./practice";

export {
  getCourseProgress,
  getLearningOverview,
  getGlobalTrends,
  getMemoryStats,
  triggerConsolidation,
  getKnowledgeGraph,
  getExamPrepPlan,
  saveStudyPlan,
  listStudyPlanBatches,
  getStudyPlans,
  listAgentTasks,
  submitAgentTask,
  approveAgentTask,
  rejectAgentTask,
  listStudyGoals,
  getNextAction,
  listTemplates,
  applyTemplate,
  getForgettingForecast,
  getMisconceptionDashboard,
  getReviewSession,
  listAgendaRuns,
  logAgentDecision,
} from "./progress";

export type {
  CourseProgress,
  MisconceptionItem,
  MisconceptionDashboard,
  LearningOverview,
  LearningTrends,
  MemoryStats,
  ForgettingPrediction,
  ForgettingForecast,
  KnowledgeGraphNode,
  KnowledgeGraphEdge,
  ReviewItem,
  ReviewSession,
  AgentTask,
  AgentTaskStepResult,
  AgentTaskReview,
  AgentTaskVerifierDiagnostics,
  NextActionResponse,
  StudyGoal,
  AgendaRun,
  AgendaDecisionLogRequest,
  StudyPlanResponse,
} from "./progress";

export {
  getLearningProfile,
  setPreference,
  getLlmRuntimeConfig,
  updateLlmRuntimeConfig,
  testLlmRuntimeConnection,
  getOllamaModels,
  listPreferenceSignals,
  dismissPreference,
  restorePreference,
  dismissSignal,
  restoreSignal,
  dismissMemory,
  restoreMemory,
} from "./preferences";

export type {
  Preference,
  MemoryProfileItem,
  LearningProfile,
  LlmRuntimeConfig,
  LlmConnectionTestResult,
  OllamaModel,
  PreferenceSignal,
} from "./preferences";

export {
  getUsageSummary,
  getExportSessionUrl,
  getAnkiExportUrl,
  getCalendarExportUrl,
} from "./usage";

export type {
  UsageSummary,
} from "./usage";

export {
  listIngestionJobs,
  syncCourse,
  createScrapeSource,
} from "./ingestion";

export type {
  IngestionJobSummary,
  SyncResult,
  ScrapeSource,
} from "./ingestion";

export {
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  markTaskNotificationsRead,
} from "./notifications";

export type {
  AppNotification,
  NotificationsResponse,
} from "./notifications";

