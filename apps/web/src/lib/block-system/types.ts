export type BlockType =
  | "notes"
  | "quiz"
  | "flashcards"
  | "progress"
  | "knowledge_graph"
  | "review"
  | "chapter_list"
  | "plan"
  | "wrong_answers"
  | "forecast"
  | "agent_insight"
  | "summary";

export type BlockSize = "small" | "medium" | "large" | "full";

export type BlockSource = "template" | "user" | "agent";

/** The four learning modes defined in the PRD. */
export type LearningMode = "course_following" | "self_paced" | "exam_prep" | "maintenance";

export interface AgentBlockMeta {
  /** Why the agent added this block */
  reason: string;
  /** Whether user can dismiss */
  dismissible: boolean;
  /** Auto-remove after this ISO date */
  expiresAt?: string;
  /** Second-tier: needs user approval before becoming active */
  needsApproval?: boolean;
  /** CTA button text for approval (e.g. "Add Flashcards") */
  approvalCta?: string;
}

export interface BlockInstance {
  id: string;
  type: BlockType;
  position: number;
  size: BlockSize;
  config: Record<string, unknown>;
  visible: boolean;
  source: BlockSource;
  agentMeta?: AgentBlockMeta;
}

export interface SpaceLayout {
  templateId: string | null;
  blocks: BlockInstance[];
  columns: 1 | 2 | 3;
  /** Active learning mode for this space. */
  mode?: LearningMode;
}
