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
  /** Locale key for the display name (`templates.<id>.name`). */
  nameKey: string;
  /** Locale key for the description (`templates.<id>.description`). */
  descriptionKey: string;
  /** Default learning mode attached to this template. */
  defaultMode: LearningMode;
  blocks: Array<Omit<BlockInstance, "id"> & { id: string }>;
  columns: 1 | 2 | 3;
}

export const TEMPLATES: Record<string, TemplateDefinition> = {
  stem_student: {
    id: "stem_student",
    nameKey: "templates.stem_student.name",
    descriptionKey: "templates.stem_student.description",
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
    nameKey: "templates.humanities_scholar.name",
    descriptionKey: "templates.humanities_scholar.description",
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
    nameKey: "templates.visual_learner.name",
    descriptionKey: "templates.visual_learner.description",
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
    nameKey: "templates.quick_reviewer.name",
    descriptionKey: "templates.quick_reviewer.description",
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
    nameKey: "templates.blank_canvas.name",
    descriptionKey: "templates.blank_canvas.description",
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

/** Templates shown in the workspace template picker (single source of truth). */
export const TEMPLATE_LIST = TEMPLATE_DISPLAY_ORDER.map((id) => TEMPLATES[id]);

// ── Learning Mode Definitions ──

export interface LearningModeDefinition {
  id: LearningMode;
  /** Locale key for the display name (`mode.<id>`). */
  nameKey: string;
  /** Locale key for the description (`mode.<id>.desc`). */
  descriptionKey: string;
  icon: string;
  /** Default block layout for this mode. */
  blocks: Array<Omit<BlockInstance, "id"> & { id: string }>;
  columns: 1 | 2 | 3;
}

export const LEARNING_MODES: Record<LearningMode, LearningModeDefinition> = {
  course_following: {
    id: "course_following",
    nameKey: "mode.course_following",
    descriptionKey: "mode.course_following.desc",
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
    nameKey: "mode.self_paced",
    descriptionKey: "mode.self_paced.desc",
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
    nameKey: "mode.exam_prep",
    descriptionKey: "mode.exam_prep.desc",
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
    nameKey: "mode.maintenance",
    descriptionKey: "mode.maintenance.desc",
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
