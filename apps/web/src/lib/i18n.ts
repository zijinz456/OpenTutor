/**
 * Internationalization (i18n) system.
 *
 * Simple key-value translation system supporting English.
 * Uses React context for language switching.
 */

export type Locale = "en";

const translations: Record<Locale, Record<string, string>> = {
  en: {
    // Navigation
    "nav.dashboard": "Dashboard",
    "nav.courses": "My Courses",
    "nav.settings": "Settings",

    // Dashboard
    "dashboard.title": "Your Courses",
    "dashboard.create": "Create Course",
    "dashboard.empty": "No courses yet. Create one to get started!",
    "dashboard.upload": "Upload Materials",

    // Course page
    "course.notes": "Notes",
    "course.quiz": "Quiz",
    "course.chat": "Chat",
    "course.flashcards": "Flashcards",
    "course.progress": "Progress",

    // Chat
    "chat.placeholder": "Ask anything about this course...",
    "chat.send": "Send",
    "chat.thinking": "Thinking...",
    "chat.empty": "Start a conversation about your course materials",

    // Quiz
    "quiz.title": "Quiz",
    "quiz.generate": "Generate Quiz from Content",
    "quiz.generating": "Generating...",
    "quiz.empty": "No quiz questions yet",
    "quiz.question": "Question",
    "quiz.of": "of",
    "quiz.correct": "correct",
    "quiz.prev": "Prev",
    "quiz.next": "Next",
    "quiz.explanation": "Explanation:",

    // Notes
    "notes.title": "AI Notes",
    "notes.toc": "Table of Contents",
    "notes.empty": "Upload course materials to generate notes",
    "notes.regenerate": "Regenerate Notes",

    // Upload
    "upload.title": "Upload Materials",
    "upload.drag": "Drag & drop files here, or click to browse",
    "upload.url": "Or paste a URL",
    "upload.supported": "Supported: PDF, PPTX, DOCX, HTML, TXT, MD",
    "upload.uploading": "Uploading...",

    // Flashcards
    "flashcard.title": "Flashcards",
    "flashcard.generate": "Generate Flashcards",
    "flashcard.front": "Question",
    "flashcard.back": "Answer",
    "flashcard.flip": "Flip",
    "flashcard.again": "Again",
    "flashcard.hard": "Hard",
    "flashcard.good": "Good",
    "flashcard.easy": "Easy",
    "flashcard.empty": "No flashcards yet",
    "flashcard.due": "Due for review",
    "flashcard.mastered": "Mastered",

    // Progress
    "progress.title": "Learning Progress",
    "progress.mastered": "Mastered",
    "progress.reviewed": "Reviewed",
    "progress.inProgress": "In Progress",
    "progress.notStarted": "Not Started",
    "progress.totalTime": "Total Study Time",
    "progress.accuracy": "Quiz Accuracy",

    // Preferences
    "pref.title": "Preferences",
    "pref.noteFormat": "Note Format",
    "pref.detailLevel": "Detail Level",
    "pref.language": "Language",
    "pref.explanationStyle": "Explanation Style",
    "pref.applyGlobal": "Apply as Long-term Habit",
    "pref.applyCourse": "Just for This Course",
    "pref.dismiss": "Don't Change",

    // Templates
    "template.title": "Learning Templates",
    "template.apply": "Apply Template",
    "template.stem": "STEM Student",
    "template.humanities": "Humanities Scholar",
    "template.language": "Language Learner",
    "template.visual": "Visual Learner",
    "template.quick": "Quick Reviewer",

    // Canvas
    "canvas.title": "Canvas Integration",
    "canvas.login": "Login to Canvas",
    "canvas.sync": "Sync Courses",
    "canvas.syncing": "Syncing...",

    // General
    "general.loading": "Loading...",
    "general.error": "Something went wrong",
    "general.save": "Save",
    "general.cancel": "Cancel",
    "general.delete": "Delete",
    "general.close": "Close",
  },
};

let currentLocale: Locale = "en";

export function setLocale(locale: Locale) {
  currentLocale = locale;
  if (typeof window !== "undefined") {
    localStorage.setItem("opentutor-locale", locale);
  }
}

const SUPPORTED_LOCALES: Locale[] = ["en"];

export function getLocale(): Locale {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("opentutor-locale") as Locale | null;
    if (saved && SUPPORTED_LOCALES.includes(saved)) {
      currentLocale = saved;
    }
  }
  return currentLocale;
}

export function t(key: string): string {
  return translations[currentLocale]?.[key] ?? translations.en[key] ?? key;
}

export function initLocale() {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("opentutor-locale") as Locale | null;
    if (saved) {
      currentLocale = saved;
    } else {
      currentLocale = "en";
    }
  }
}
