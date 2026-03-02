/**
 * Internationalization (i18n) system.
 *
 * Simple key-value translation system supporting English.
 * Uses React context for language switching.
 */

export type Locale = "en" | "zh";

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

    // Settings
    "settings.title": "Settings",
    "settings.language": "Language",
    "settings.theme": "Appearance",
    "settings.provider": "Provider Connections",
  },
  zh: {
    // Navigation
    "nav.dashboard": "仪表盘",
    "nav.courses": "我的课程",
    "nav.settings": "设置",

    // Dashboard
    "dashboard.title": "你的课程",
    "dashboard.create": "创建课程",
    "dashboard.empty": "还没有课程，创建一个开始学习吧！",
    "dashboard.upload": "上传学习资料",

    // Course page
    "course.notes": "笔记",
    "course.quiz": "测验",
    "course.chat": "问答",
    "course.flashcards": "闪卡",
    "course.progress": "进度",

    // Chat
    "chat.placeholder": "问任何关于这门课的问题...",
    "chat.send": "发送",
    "chat.thinking": "思考中...",
    "chat.empty": "开始关于你课程资料的对话",

    // Quiz
    "quiz.title": "测验",
    "quiz.generate": "从内容生成测验",
    "quiz.generating": "生成中...",
    "quiz.empty": "还没有测验题目",
    "quiz.question": "题目",
    "quiz.of": "/",
    "quiz.correct": "正确",
    "quiz.prev": "上一题",
    "quiz.next": "下一题",
    "quiz.explanation": "解析：",

    // Notes
    "notes.title": "AI 笔记",
    "notes.toc": "目录",
    "notes.empty": "上传课程资料以生成笔记",
    "notes.regenerate": "重新生成笔记",

    // Upload
    "upload.title": "上传资料",
    "upload.drag": "拖拽文件到此处，或点击浏览",
    "upload.url": "或粘贴链接",
    "upload.supported": "支持格式：PDF、PPTX、DOCX、HTML、TXT、MD",
    "upload.uploading": "上传中...",

    // Flashcards
    "flashcard.title": "闪卡",
    "flashcard.generate": "生成闪卡",
    "flashcard.front": "问题",
    "flashcard.back": "答案",
    "flashcard.flip": "翻转",
    "flashcard.again": "再来",
    "flashcard.hard": "困难",
    "flashcard.good": "良好",
    "flashcard.easy": "简单",
    "flashcard.empty": "还没有闪卡",
    "flashcard.due": "待复习",
    "flashcard.mastered": "已掌握",

    // Progress
    "progress.title": "学习进度",
    "progress.mastered": "已掌握",
    "progress.reviewed": "已复习",
    "progress.inProgress": "学习中",
    "progress.notStarted": "未开始",
    "progress.totalTime": "总学习时间",
    "progress.accuracy": "测验正确率",

    // Preferences
    "pref.title": "偏好设置",
    "pref.noteFormat": "笔记格式",
    "pref.detailLevel": "详细程度",
    "pref.language": "语言",
    "pref.explanationStyle": "讲解风格",
    "pref.applyGlobal": "设为长期习惯",
    "pref.applyCourse": "仅用于此课程",
    "pref.dismiss": "不更改",

    // Templates
    "template.title": "学习模板",
    "template.apply": "应用模板",
    "template.stem": "理工科学生",
    "template.humanities": "文科学者",
    "template.language": "语言学习者",
    "template.visual": "视觉学习者",
    "template.quick": "快速复习者",

    // Canvas
    "canvas.title": "Canvas 集成",
    "canvas.login": "登录 Canvas",
    "canvas.sync": "同步课程",
    "canvas.syncing": "同步中...",

    // General
    "general.loading": "加载中...",
    "general.error": "出了点问题",
    "general.save": "保存",
    "general.cancel": "取消",
    "general.delete": "删除",
    "general.close": "关闭",

    // Settings
    "settings.title": "设置",
    "settings.language": "语言",
    "settings.theme": "外观",
    "settings.provider": "服务商连接",
  },
};

let currentLocale: Locale = "en";

export function setLocale(locale: Locale) {
  currentLocale = locale;
  if (typeof window !== "undefined") {
    localStorage.setItem("opentutor-locale", locale);
  }
}

const SUPPORTED_LOCALES: Locale[] = ["en", "zh"];

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
