import type { BlockInstance, SpaceLayout, BlockType, BlockSize, LearningMode } from "./types";

/** Helper to create a block instance for template definitions. */
function b(
  type: BlockType,
  size: BlockSize,
  config: Record<string, unknown> = {},
  position = 0,
): Omit<BlockInstance, "id"> & { id: string } {
  return {
    id: "", // will be assigned at apply time
    type,
    position,
    size,
    config,
    visible: true,
    source: "template",
  };
}

export interface TemplateDefinition {
  id: string;
  name: string;
  nameZh: string;
  description: string;
  descriptionZh: string;
  /** Default learning mode attached to this template. */
  defaultMode: LearningMode;
  blocks: Array<Omit<BlockInstance, "id"> & { id: string }>;
  columns: 1 | 2 | 3;
}

export const TEMPLATES: Record<string, TemplateDefinition> = {
  stem_student: {
    id: "stem_student",
    name: "STEM Student",
    nameZh: "理工科学生",
    description: "Step-by-step notes, adaptive quizzes, knowledge graph",
    descriptionZh: "分步笔记、自适应测验、知识图谱",
    defaultMode: "course_following",
    columns: 2,
    blocks: [
      b("chapter_list", "full", {}),
      b("notes", "large", { note_format: "step_by_step" }),
      b("quiz", "medium", { difficulty: "adaptive" }),
      b("knowledge_graph", "medium"),
      b("progress", "small"),
    ],
  },
  humanities_scholar: {
    id: "humanities_scholar",
    name: "Humanities Scholar",
    nameZh: "人文学者",
    description: "Rich narrative notes, review sessions, reading progress",
    descriptionZh: "叙事性笔记、复习环节、阅读进度",
    defaultMode: "course_following",
    columns: 2,
    blocks: [
      b("chapter_list", "full"),
      b("notes", "large", { note_format: "summary" }),
      b("review", "medium"),
      b("progress", "small"),
    ],
  },
  visual_learner: {
    id: "visual_learner",
    name: "Visual Learner",
    nameZh: "视觉学习者",
    description: "Knowledge graph prominent, mind map notes, visual aids",
    descriptionZh: "知识图谱突出、思维导图笔记、视觉辅助",
    defaultMode: "self_paced",
    columns: 2,
    blocks: [
      b("chapter_list", "full"),
      b("knowledge_graph", "large"),
      b("notes", "medium", { note_format: "mind_map" }),
      b("quiz", "medium", { difficulty: "adaptive" }),
      b("progress", "small"),
    ],
  },
  quick_reviewer: {
    id: "quick_reviewer",
    name: "Quick Reviewer",
    nameZh: "快速复习",
    description: "Quiz-heavy, flashcards, error analysis",
    descriptionZh: "大量刷题、闪卡、错题分析",
    defaultMode: "exam_prep",
    columns: 2,
    blocks: [
      b("chapter_list", "full"),
      b("quiz", "large", { difficulty: "hard" }),
      b("flashcards", "medium"),
      b("wrong_answers", "medium"),
      b("progress", "small"),
    ],
  },
  blank_canvas: {
    id: "blank_canvas",
    name: "Blank Canvas",
    nameZh: "空白画布",
    description: "Start from scratch and build your own space.",
    descriptionZh: "从零开始，自定义你的学习空间。",
    defaultMode: "self_paced",
    columns: 2,
    blocks: [],
  },
};

const TEMPLATE_DISPLAY_ORDER = [
  "stem_student",
  "humanities_scholar",
  "visual_learner",
  "quick_reviewer",
  "blank_canvas",
] as const;

/** Templates shown in onboarding/template picker. */
export const TEMPLATE_LIST = TEMPLATE_DISPLAY_ORDER.map((id) => TEMPLATES[id]);

// ── Learning Mode Definitions ──

export interface LearningModeDefinition {
  id: LearningMode;
  name: string;
  nameZh: string;
  description: string;
  descriptionZh: string;
  icon: string;
  /** Default block layout for this mode. */
  blocks: Array<Omit<BlockInstance, "id"> & { id: string }>;
  columns: 1 | 2 | 3;
}

export const LEARNING_MODES: Record<LearningMode, LearningModeDefinition> = {
  course_following: {
    id: "course_following",
    name: "Course Following",
    nameZh: "跟课模式",
    description: "Timeline-driven. Deadlines, lecture notes, and syllabus tracking.",
    descriptionZh: "按时间线驱动，追踪截止日期、课堂笔记和教学大纲。",
    icon: "GraduationCap",
    columns: 2,
    blocks: [
      b("chapter_list", "full"),
      b("notes", "large"),
      b("quiz", "medium"),
      b("flashcards", "medium"),
    ],
  },
  self_paced: {
    id: "self_paced",
    name: "Self-Paced",
    nameZh: "自学模式",
    description: "Exploration-driven. Notes, flashcards, and progress tracking.",
    descriptionZh: "以探索为驱动，笔记、闪卡与进度追踪。",
    icon: "Compass",
    columns: 2,
    blocks: [
      b("notes", "large"),
      b("flashcards", "medium"),
      b("progress", "medium"),
    ],
  },
  exam_prep: {
    id: "exam_prep",
    name: "Exam Prep",
    nameZh: "备考模式",
    description: "Practice-heavy. Quiz, progress tracking, and study planning.",
    descriptionZh: "大量练习，聚焦测验、进度追踪与学习计划。",
    icon: "Clock",
    columns: 2,
    blocks: [
      b("quiz", "large", { difficulty: "hard" }),
      b("progress", "medium"),
      b("plan", "medium"),
    ],
  },
  maintenance: {
    id: "maintenance",
    name: "Maintenance",
    nameZh: "维护模式",
    description: "Minimal. LECTOR review and knowledge retention only.",
    descriptionZh: "极简模式，仅保留 LECTOR 复习与知识保持。",
    icon: "Shield",
    columns: 2,
    blocks: [
      b("review", "large"),
      b("flashcards", "medium"),
    ],
  },
};

export const LEARNING_MODE_LIST = Object.values(LEARNING_MODES);

/** Generate a SpaceLayout from a template, assigning unique IDs and positions. */
export function buildLayoutFromTemplate(templateId: string): SpaceLayout | null {
  const template = TEMPLATES[templateId];
  if (!template) return null;

  const blocks: BlockInstance[] = template.blocks.map((block, index) => ({
    ...block,
    id: `${templateId}-${block.type}-${index}`,
    position: index,
  }));

  return {
    templateId,
    blocks,
    columns: template.columns,
    mode: template.defaultMode,
  };
}

/** Generate a SpaceLayout from a learning mode, assigning unique IDs and positions. */
export function buildLayoutFromMode(mode: LearningMode): SpaceLayout {
  const def = LEARNING_MODES[mode];
  const blocks: BlockInstance[] = def.blocks.map((block, index) => ({
    ...block,
    id: `mode-${mode}-${block.type}-${index}`,
    position: index,
  }));

  return {
    templateId: null,
    blocks,
    columns: def.columns,
    mode,
  };
}
