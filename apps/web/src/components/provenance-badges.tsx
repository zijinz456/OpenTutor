"use client";

import { Badge } from "@/components/ui/badge";
import type { AgentTask, ChatProvenance } from "@/lib/api";

interface ProvenanceBadgesProps {
  provenance?: ChatProvenance | null;
  task?: AgentTask;
  compact?: boolean;
}

function normalizeTaskProvenance(task?: AgentTask): ChatProvenance | null {
  if (!task) return null;
  if (task.provenance && typeof task.provenance === "object") {
    return task.provenance as ChatProvenance;
  }
  const metadataProv = task.metadata_json?.["provenance"];
  if (metadataProv && typeof metadataProv === "object") {
    return metadataProv as ChatProvenance;
  }
  const resultProv = task.result_json?.["provenance"];
  if (resultProv && typeof resultProv === "object") {
    return resultProv as ChatProvenance;
  }
  return {
    workflow: task.task_type,
    generated: true,
    source_labels: [task.source, "generated"],
  };
}

function buildBadgeLabels(provenance: ChatProvenance | null): string[] {
  if (!provenance) return [];
  const labels: string[] = [];

  if (provenance.workflow) labels.push(`workflow ${provenance.workflow}`);
  if (provenance.scene) labels.push(`scene ${provenance.scene}`);
  if (typeof provenance.content_count === "number" && provenance.content_count > 0) {
    labels.push(`course ${provenance.content_count}`);
  }
  if (typeof provenance.memory_count === "number" && provenance.memory_count > 0) {
    labels.push(`memory ${provenance.memory_count}`);
  }
  if (typeof provenance.tool_count === "number" && provenance.tool_count > 0) {
    labels.push(`tools ${provenance.tool_count}`);
  }
  if (provenance.scheduler_trigger) labels.push("scheduled");
  if (provenance.user_input) labels.push("user input");
  if (provenance.generated) labels.push("generated");

  for (const label of provenance.source_labels ?? []) {
    if (label === "workflow" || label === "generated" || label === "course" || label === "memory" || label === "user_input") {
      continue;
    }
    labels.push(label.replaceAll("_", " "));
  }

  return [...new Set(labels)];
}

export function ProvenanceBadges({ provenance, task, compact = false }: ProvenanceBadgesProps) {
  const resolved = provenance ?? normalizeTaskProvenance(task);
  const labels = buildBadgeLabels(resolved);
  if (labels.length === 0) return null;

  return (
    <div className={`flex flex-wrap gap-1.5 ${compact ? "" : "mt-2"}`}>
      {labels.map((label) => (
        <Badge key={label} variant="outline">
          {label}
        </Badge>
      ))}
    </div>
  );
}
